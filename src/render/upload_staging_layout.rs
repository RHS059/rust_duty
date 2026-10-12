//! Checked, GPU-independent layout and retention accounting for upload sources.

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Segment {
    pub(super) source_offset: u64,
    pub(super) logical_len: usize,
    pub(super) copy_len: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Pack {
    pub(super) segments: Vec<Segment>,
    pub(super) required_bytes: u64,
    pub(super) capacity: u64,
}

impl Pack {
    /// Plan up to three payloads in one MAP_WRITE | COPY_SRC buffer.
    ///
    /// Nonempty mapped ranges start at eight-byte-aligned source offsets; copy
    /// lengths include four-byte padding without changing the logical lengths.
    /// Empty segments retain their position with offset/copy length zero and
    /// must be skipped by the caller. Empty/all-zero input returns `Ok(None)`.
    ///
    /// Validate every payload before choosing the fallback: `Ok(None)` also
    /// means individually valid copies cannot fit together under the device
    /// limit. Invalid individual sizes or arithmetic/address-size overflow are
    /// errors, so falling back cannot hide an invalid later payload.
    pub(super) fn new(lengths: &[usize], max_buffer_size: u64) -> Result<Option<Self>, String> {
        if lengths.len() > 3 {
            return Err("staging upload supports at most three payloads".into());
        }

        let mut segments = Vec::with_capacity(lengths.len());
        for &logical_len in lengths {
            let logical_bytes =
                u64::try_from(logical_len).map_err(|_| "staging payload length exceeds u64")?;
            let copy_len = align_up(logical_bytes, 4).ok_or("staging copy length overflow")?;
            usize::try_from(copy_len).map_err(|_| "staging copy length exceeds address space")?;
            if copy_len > max_buffer_size {
                return Err("staging payload exceeds device buffer limit".into());
            }
            segments.push(Segment {
                source_offset: 0,
                logical_len,
                copy_len,
            });
        }

        let mut required_bytes = 0;
        for segment in &mut segments {
            if segment.copy_len == 0 {
                continue;
            }
            segment.source_offset =
                align_up(required_bytes, 8).ok_or("staging source offset overflow")?;
            required_bytes = segment
                .source_offset
                .checked_add(segment.copy_len)
                .ok_or("staging packed size overflow")?;
            usize::try_from(required_bytes)
                .map_err(|_| "staging packed size exceeds address space")?;
        }
        if required_bytes == 0 || required_bytes > max_buffer_size {
            return Ok(None);
        }

        // Power-of-two growth is optional. An exact-sized allocation remains
        // valid when rounding would overflow or exceed either usable limit.
        let capacity = required_bytes
            .checked_next_power_of_two()
            .filter(|&bytes| bytes <= max_buffer_size && usize::try_from(bytes).is_ok())
            .unwrap_or(required_bytes);
        Ok(Some(Self {
            segments,
            required_bytes,
            capacity,
        }))
    }
}

fn align_up(value: u64, alignment: u64) -> Option<u64> {
    value
        .checked_add(alignment - 1)
        .map(|bytes| bytes & !(alignment - 1))
}

/// Decide whether one additional source chunk fits both retention limits.
///
/// `retained` and `live_chunks` include every live chunk, including submitted
/// chunks waiting for remapping. Pending chunks cannot be discounted merely
/// because they are not currently reusable.
pub(super) fn can_allocate(
    retained: u64,
    capacity: u64,
    live_chunks: usize,
    byte_budget: u64,
    slot_budget: usize,
) -> bool {
    retained
        .checked_add(capacity)
        .is_some_and(|bytes| bytes <= byte_budget)
        && live_chunks
            .checked_add(1)
            .is_some_and(|chunks| chunks <= slot_budget)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn six_byte_indices_keep_their_logical_length() {
        let pack = Pack::new(&[16, 6, 64], 1024).unwrap().unwrap();
        assert_eq!(
            pack.segments,
            vec![
                Segment {
                    source_offset: 0,
                    logical_len: 16,
                    copy_len: 16,
                },
                Segment {
                    source_offset: 16,
                    logical_len: 6,
                    copy_len: 8,
                },
                Segment {
                    source_offset: 24,
                    logical_len: 64,
                    copy_len: 64,
                },
            ]
        );
        assert_eq!(pack.required_bytes, 88);
        assert_eq!(pack.capacity, 128);
    }

    #[test]
    fn four_mod_eight_copies_leave_aligned_source_gaps() {
        let pack = Pack::new(&[4, 12, 4], 1024).unwrap().unwrap();
        let offsets: Vec<_> = pack.segments.iter().map(|s| s.source_offset).collect();
        assert_eq!(offsets, [0, 8, 24]);
        assert_eq!(pack.required_bytes, 28);
        assert_eq!(pack.capacity, 32);
    }

    #[test]
    fn exact_power_of_two_does_not_grow() {
        let pack = Pack::new(&[8, 8], 1024).unwrap().unwrap();
        assert_eq!(pack.required_bytes, 16);
        assert_eq!(pack.capacity, 16);
    }

    #[test]
    fn empty_segments_keep_their_place_without_consuming_space() {
        let pack = Pack::new(&[4, 0, 4], 1024).unwrap().unwrap();
        assert_eq!(
            pack.segments[1],
            Segment {
                source_offset: 0,
                logical_len: 0,
                copy_len: 0,
            }
        );
        assert_eq!(pack.segments[2].source_offset, 8);
        assert_eq!(pack.required_bytes, 12);
        assert_eq!(pack.capacity, 16);
        let pack = Pack::new(&[0, 4, 0], 1024).unwrap().unwrap();
        assert_eq!(pack.required_bytes, 4);
        assert_eq!(pack.capacity, 4);
    }

    #[test]
    fn empty_and_all_zero_input_are_noops() {
        assert_eq!(Pack::new(&[], 0), Ok(None));
        assert_eq!(Pack::new(&[0], 0), Ok(None));
        assert_eq!(Pack::new(&[0, 0, 0], 0), Ok(None));
    }

    #[test]
    fn more_than_three_payloads_are_rejected() {
        assert!(Pack::new(&[4, 4, 4, 4], 1024).is_err());
        assert!(Pack::new(&[0, 0, 0, 0], 1024).is_err());
    }

    #[test]
    fn exact_required_capacity_is_used_when_growth_exceeds_device_limit() {
        for limit in [20, 24] {
            let pack = Pack::new(&[12, 4], limit).unwrap().unwrap();
            assert_eq!(pack.required_bytes, 20);
            assert_eq!(pack.capacity, 20);
        }
    }

    #[test]
    fn individually_valid_copies_fall_back_when_the_pack_exceeds_the_limit() {
        assert_eq!(Pack::new(&[12, 12], 16), Ok(None));
        // The alignment gap, rather than the sum of payload lengths, can be
        // what pushes an otherwise valid pair beyond the source-buffer limit.
        assert_eq!(Pack::new(&[4, 4], 8), Ok(None));
    }

    #[test]
    fn invalid_payload_is_not_hidden_by_an_earlier_packed_fallback() {
        assert!(Pack::new(&[12, 12, 17], 16).is_err());
        assert!(Pack::new(&[5], 6).is_err());
        assert!(Pack::new(&[1], 0).is_err());
    }

    #[test]
    fn copy_padding_and_source_alignment_are_checked() {
        assert_eq!(align_up(6, 4), Some(8));
        assert_eq!(align_up(12, 8), Some(16));
        assert_eq!(align_up(u64::MAX - 3, 4), Some(u64::MAX - 3));
        assert_eq!(align_up(u64::MAX, 4), None);
        assert_eq!(align_up(u64::MAX - 3, 8), None);
        assert!(Pack::new(&[usize::MAX], u64::MAX).is_err());
    }

    #[cfg(target_pointer_width = "64")]
    #[test]
    fn packed_size_and_source_offset_overflow_are_errors() {
        assert!(Pack::new(&[usize::MAX - 7, 8], u64::MAX).is_err());
        assert!(Pack::new(&[usize::MAX - 3, 4], u64::MAX).is_err());
    }

    #[cfg(target_pointer_width = "64")]
    #[test]
    fn power_of_two_overflow_keeps_a_valid_exact_capacity() {
        let required = usize::MAX - 3;
        let pack = Pack::new(&[required], u64::MAX).unwrap().unwrap();
        assert_eq!(pack.required_bytes, required as u64);
        assert_eq!(pack.capacity, required as u64);
    }

    #[cfg(target_pointer_width = "32")]
    #[test]
    fn address_space_limits_are_checked_for_packing_and_growth() {
        assert!(Pack::new(&[usize::MAX - 7, 8], u64::MAX).is_err());
        let required = usize::MAX - 3;
        let pack = Pack::new(&[required], u64::MAX).unwrap().unwrap();
        assert_eq!(pack.capacity, required as u64);
    }

    #[test]
    fn budget_includes_pending_chunks_in_bytes_and_slots() {
        // Three reusable and four pending chunks each retain eight bytes.
        assert!(can_allocate(56, 8, 7, 64, 8));
        assert!(!can_allocate(56, 8, 7, 63, 8));
        assert!(!can_allocate(56, 8, 7, 64, 7));
        assert!(!can_allocate(64, 8, 8, 128, 8));
    }

    #[test]
    fn budget_arithmetic_overflow_is_rejected() {
        assert!(!can_allocate(u64::MAX, 1, 0, u64::MAX, 8));
        assert!(!can_allocate(0, 4, usize::MAX, 4, usize::MAX));
        assert!(!can_allocate(0, 4, 0, 4, 0));
        assert!(!can_allocate(0, 4, 0, 0, 1));
    }
}
