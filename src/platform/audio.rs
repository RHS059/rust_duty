//! Synthesized one-shot audio, independent of the renderer and window backend.
#[cfg(feature = "audio")]
use rodio::{source::Buffered, Decoder, DeviceSinkBuilder, MixerDeviceSink, Source};
#[cfg(feature = "audio")]
use std::io::Cursor;

#[cfg(feature = "audio")]
type Sound = Buffered<Decoder<Cursor<Vec<u8>>>>;

pub struct SoundBank {
    // Keep the device alive for the whole bank lifetime; dropping it stops playback.
    #[cfg(feature = "audio")]
    output: Option<MixerDeviceSink>,
    #[cfg(feature = "audio")]
    sounds: [Option<Sound>; 4],
    pub muted: bool,
}

impl SoundBank {
    pub async fn new() -> Self {
        Self {
            // A missing output device must not prevent captures or gameplay.
            #[cfg(feature = "audio")]
            output: DeviceSinkBuilder::open_default_sink().ok(),
            #[cfg(feature = "audio")]
            sounds: std::array::from_fn(|kind| {
                Decoder::new_wav(Cursor::new(synthesize(kind as u8)))
                    .ok()
                    .map(Source::buffered)
            }),
            muted: false,
        }
    }

    pub fn play(&self, kind: u8) {
        if self.muted {
            return;
        }
        #[cfg(feature = "audio")]
        {
            let (index, volume) = sound_parameters(kind);
            if let (Some(output), Some(sound)) = (&self.output, &self.sounds[index]) {
                // Each clone starts at the beginning. Add directly to the mixer so
                // overlapping effects play together, rather than queueing serially.
                output.mixer().add(sound.clone().amplify(volume));
            }
        }
        #[cfg(not(feature = "audio"))]
        let _ = kind;
    }
}

#[cfg(any(feature = "audio", test))]
fn sound_parameters(kind: u8) -> (usize, f32) {
    match kind {
        0 => (0, 0.28),
        1 => (1, 0.20),
        2 => (2, 0.13),
        _ => (3, 0.16),
    }
}

#[cfg(any(feature = "audio", test))]
fn synthesize(kind: u8) -> Vec<u8> {
    let rate = 22050_u32;
    let duration = if kind == 0 { 0.22 } else { 0.12 };
    let count = (rate as f32 * duration) as usize;
    let mut pcm = Vec::with_capacity(count * 2);
    let mut seed = 0x1eaf1234_u32;
    for i in 0..count {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        let noise = seed as f64 / u32::MAX as f64 * 2. - 1.;
        let t = i as f64 / rate as f64;
        let sample = match kind {
            0 => {
                noise * (-t * 40.).exp() * 0.70
                    + (std::f64::consts::TAU * (100. * t - 95. * t * t)).sin()
                        * (-t * 24.).exp()
                        * 0.28
            }
            1 => (std::f64::consts::TAU * 1750. * t).sin() * (-t * 45.).exp() * 0.5,
            2 => {
                noise * (-t * 40.).exp() * 0.65
                    + (std::f64::consts::TAU * 75. * t).sin() * (-t * 50.).exp() * 0.2
            }
            _ => {
                noise * (-t * 65.).exp() * 0.5
                    + (std::f64::consts::TAU * 420. * t).sin() * (-t * 50.).exp() * 0.15
            }
        };
        let edge = (i as f64 / 8.).min(1.);
        let v =
            (sample * edge * 0.9 * i16::MAX as f64).clamp(i16::MIN as f64, i16::MAX as f64) as i16;
        pcm.extend(v.to_le_bytes());
    }
    let bytes = pcm.len() as u32;
    let mut out = Vec::with_capacity(44 + pcm.len());
    out.extend(b"RIFF");
    out.extend((36 + bytes).to_le_bytes());
    out.extend(b"WAVEfmt ");
    out.extend(16_u32.to_le_bytes());
    out.extend(1_u16.to_le_bytes());
    out.extend(1_u16.to_le_bytes());
    out.extend(rate.to_le_bytes());
    out.extend((rate * 2).to_le_bytes());
    out.extend(2_u16.to_le_bytes());
    out.extend(16_u16.to_le_bytes());
    out.extend(b"data");
    out.extend(bytes.to_le_bytes());
    out.extend(pcm);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u16_at(bytes: &[u8], offset: usize) -> u16 {
        u16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap())
    }

    fn u32_at(bytes: &[u8], offset: usize) -> u32 {
        u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
    }

    #[test]
    fn synthesized_wavs_preserve_pcm_format_and_duration() {
        for (kind, samples) in [(0, 4851), (1, 2646), (2, 2646), (3, 2646)] {
            let wav = synthesize(kind);
            assert_eq!(&wav[0..4], b"RIFF");
            assert_eq!(u32_at(&wav, 4) as usize, wav.len() - 8);
            assert_eq!(&wav[8..16], b"WAVEfmt ");
            assert_eq!(u32_at(&wav, 16), 16, "PCM format chunk size");
            assert_eq!(u16_at(&wav, 20), 1, "integer PCM");
            assert_eq!(u16_at(&wav, 22), 1, "mono");
            assert_eq!(u32_at(&wav, 24), 22050, "sample rate");
            assert_eq!(u32_at(&wav, 28), 44100, "byte rate");
            assert_eq!(u16_at(&wav, 32), 2, "block alignment");
            assert_eq!(u16_at(&wav, 34), 16, "sample depth");
            assert_eq!(&wav[36..40], b"data");
            assert_eq!(u32_at(&wav, 40) as usize, samples * 2);
            assert_eq!(wav.len(), 44 + samples * 2);
            assert_eq!(&wav[44..46], &[0, 0], "attack starts at zero");
            assert!(wav[46..].iter().any(|byte| *byte != 0));
        }
    }

    #[test]
    fn synthesis_is_repeatable_and_effects_are_distinct() {
        let sounds = std::array::from_fn::<_, 4, _>(|kind| synthesize(kind as u8));
        for (index, sound) in sounds.iter().enumerate() {
            assert_eq!(*sound, synthesize(index as u8));
            for other in &sounds[index + 1..] {
                assert_ne!(sound, other);
            }
        }
        assert_eq!(synthesize(u8::MAX), sounds[3]);
    }

    #[test]
    fn trigger_mapping_and_volumes_are_unchanged() {
        assert_eq!(sound_parameters(0), (0, 0.28));
        assert_eq!(sound_parameters(1), (1, 0.20));
        assert_eq!(sound_parameters(2), (2, 0.13));
        for kind in 3..=u8::MAX {
            assert_eq!(sound_parameters(kind), (3, 0.16));
        }
    }

    #[test]
    fn playback_without_a_device_is_safe_with_or_without_mute() {
        let mut bank = SoundBank {
            #[cfg(feature = "audio")]
            output: None,
            #[cfg(feature = "audio")]
            sounds: std::array::from_fn(|_| None),
            muted: false,
        };
        for muted in [false, true] {
            bank.muted = muted;
            for kind in 0..=u8::MAX {
                bank.play(kind);
            }
            assert_eq!(bank.muted, muted);
        }
    }

    #[cfg(feature = "audio")]
    #[test]
    fn rodio_decodes_every_synthesized_sample_without_a_device() {
        for kind in 0..4 {
            let wav = synthesize(kind);
            let decoded = Decoder::new_wav(Cursor::new(wav.clone())).unwrap();
            assert_eq!(decoded.channels().get(), 1);
            assert_eq!(decoded.sample_rate().get(), 22050);
            let actual: Vec<_> = decoded.collect();
            let expected: Vec<_> = wav[44..]
                .as_chunks::<2>()
                .0
                .iter()
                .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]) as f32 / 32768.0)
                .collect();
            assert_eq!(actual, expected);
        }
    }
}
