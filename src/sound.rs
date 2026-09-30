//! Synthesized in memory. No samples, recordings, or game assets.
#[cfg(feature = "audio")]
use macroquad::audio::{load_sound_from_bytes, play_sound, PlaySoundParams, Sound};
pub struct SoundBank {
    #[cfg(feature = "audio")]
    shot: Option<Sound>,
    #[cfg(feature = "audio")]
    hit: Option<Sound>,
    #[cfg(feature = "audio")]
    step: Option<Sound>,
    #[cfg(feature = "audio")]
    reload: Option<Sound>,
    pub muted: bool,
}
impl SoundBank {
    pub async fn new() -> Self {
        Self {
            #[cfg(feature = "audio")]
            shot: load_sound_from_bytes(&synthesize(0)).await.ok(),
            #[cfg(feature = "audio")]
            hit: load_sound_from_bytes(&synthesize(1)).await.ok(),
            #[cfg(feature = "audio")]
            step: load_sound_from_bytes(&synthesize(2)).await.ok(),
            #[cfg(feature = "audio")]
            reload: load_sound_from_bytes(&synthesize(3)).await.ok(),
            muted: false,
        }
    }
    pub fn play(&self, kind: u8) {
        if self.muted {
            return;
        }
        #[cfg(feature = "audio")]
        {
            let (sound, volume) = match kind {
                0 => (&self.shot, 0.28),
                1 => (&self.hit, 0.20),
                2 => (&self.step, 0.13),
                _ => (&self.reload, 0.16),
            };
            if let Some(sound) = sound {
                play_sound(
                    sound,
                    PlaySoundParams {
                        looped: false,
                        volume,
                    },
                );
            }
        }
        #[cfg(not(feature = "audio"))]
        let _ = kind;
    }
}
#[cfg(feature = "audio")]
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
