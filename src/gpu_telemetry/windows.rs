//! Small, read-only binding to the Windows inbox PDH API. No shell, vendor DLL,
//! elevation, registry edits, driver installation, or perf-counter repair.
use super::{aggregate, CounterResult, CounterValue, Provider};
use serde_json::Value;
use std::mem::size_of;
use std::ptr;

const MORE_DATA: u32 = 0x8000_07d2;
// NOSCALE preserves byte units instead of applying a provider display scale.
const FORMAT_DOUBLE_NO_CAP: u32 = 0x200 | 0x1000 | 0x8000;
const MAX_BUFFER: u32 = 4 * 1024 * 1024;
const MAX_INSTANCES: u32 = 65_536;
const PATHS: [&str; 5] = [
    "\\GPU Engine(*)\\Utilization Percentage",
    "\\GPU Process Memory(*)\\Dedicated Usage",
    "\\GPU Process Memory(*)\\Shared Usage",
    "\\GPU Adapter Memory(*)\\Dedicated Usage",
    "\\GPU Adapter Memory(*)\\Shared Usage",
];

#[repr(C)]
#[derive(Clone, Copy)]
union FormattedNumber {
    double_value: f64,
}
#[repr(C)]
#[derive(Clone, Copy)]
struct FormattedValue {
    status: u32,
    number: FormattedNumber,
}
#[repr(C)]
#[derive(Clone, Copy)]
struct FormattedItem {
    name: *const u16,
    value: FormattedValue,
}

#[cfg_attr(windows, link(name = "pdh"))]
extern "system" {
    fn PdhOpenQueryW(source: *const u16, user: usize, query: *mut isize) -> u32;
    fn PdhAddEnglishCounterW(
        query: isize,
        path: *const u16,
        user: usize,
        counter: *mut isize,
    ) -> u32;
    fn PdhCollectQueryData(query: isize) -> u32;
    fn PdhGetFormattedCounterArrayW(
        counter: isize,
        format: u32,
        bytes: *mut u32,
        count: *mut u32,
        items: *mut FormattedItem,
    ) -> u32;
    fn PdhCloseQuery(query: isize) -> u32;
}

pub(super) struct PdhProvider {
    query: isize,
    counters: [Result<isize, String>; 5],
    initial: bool,
    prime_error: Option<String>,
}
impl PdhProvider {
    pub(super) fn new() -> Result<Self, String> {
        let mut query = 0;
        // SAFETY: output points to a live isize; null selects live local data.
        check(
            unsafe { PdhOpenQueryW(ptr::null(), 0, &mut query) },
            "PdhOpenQueryW",
        )?;
        let counters = PATHS.map(|path| {
            let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
            let mut counter = 0;
            // English paths are localized by PDH; the wildcard is intentionally
            // retained for PdhGetFormattedCounterArrayW (not scalar reads).
            // SAFETY: query and NUL-terminated path live for the complete call.
            check(
                unsafe { PdhAddEnglishCounterW(query, wide.as_ptr(), 0, &mut counter) },
                path,
            )
            .map(|()| counter)
        });
        // Rate counters require two observations. This primes the first; the
        // first exported row explicitly reports warm-up, never a made-up zero.
        // SAFETY: this worker exclusively owns the live query.
        let prime_error = check(
            unsafe { PdhCollectQueryData(query) },
            "prime PdhCollectQueryData",
        )
        .err();
        Ok(Self {
            query,
            counters,
            initial: true,
            prime_error,
        })
    }
    fn query(&self, index: usize) -> CounterResult {
        let handle = *self.counters[index].as_ref().map_err(Clone::clone)?;
        // Instances can change between the required size/data calls. Retry
        // with a fresh zero-size probe rather than trusting MORE_DATA's size.
        for _ in 0..3 {
            let mut bytes = 0;
            let mut count = 0;
            // SAFETY: size probe uses no data buffer and valid output pointers.
            let status = unsafe {
                PdhGetFormattedCounterArrayW(
                    handle,
                    FORMAT_DOUBLE_NO_CAP,
                    &mut bytes,
                    &mut count,
                    ptr::null_mut(),
                )
            };
            if status == 0 && count == 0 {
                return Ok(Vec::new());
            }
            if status != MORE_DATA {
                return Err(error(status, "size GPU counter array"));
            }
            if bytes == 0 || bytes > MAX_BUFFER || count > MAX_INSTANCES {
                return Err("GPU counter array exceeds bounded collection capacity".into());
            }
            // u64 allocation provides alignment for the native structs and
            // double-valued union; bytes, not element count, is passed to PDH.
            let mut buffer = vec![0_u64; (bytes as usize).div_ceil(size_of::<u64>())];
            // SAFETY: buffer has at least bytes accessible/aligned bytes; all
            // pointers are valid during this synchronous API call.
            let status = unsafe {
                PdhGetFormattedCounterArrayW(
                    handle,
                    FORMAT_DOUBLE_NO_CAP,
                    &mut bytes,
                    &mut count,
                    buffer.as_mut_ptr().cast(),
                )
            };
            if status == MORE_DATA {
                continue;
            }
            check(status, "read GPU counter array")?;
            return decode(&buffer, bytes as usize, count as usize);
        }
        Err("GPU instances changed during all three bounded array reads".into())
    }
}
impl Provider for PdhProvider {
    fn sample(&mut self) -> Value {
        let values = if self.initial {
            self.initial = false;
            self.counters.clone().map(|counter| {
                counter.and_then(|_| {
                    Err(self.prime_error.clone().unwrap_or_else(|| {
                        "warming_up; rate counters require two observations".into()
                    }))
                })
            })
        } else {
            // SAFETY: exclusively owned query remains open until Drop.
            match check(
                unsafe { PdhCollectQueryData(self.query) },
                "PdhCollectQueryData",
            ) {
                Ok(()) => std::array::from_fn(|index| self.query(index)),
                Err(error) => std::array::from_fn(|_| Err(error.clone())),
            }
        };
        let [engine, process_dedicated, process_shared, adapter_dedicated, adapter_shared] = values;
        aggregate(
            engine,
            process_dedicated,
            process_shared,
            adapter_dedicated,
            adapter_shared,
            std::process::id(),
        )
    }
}
impl Drop for PdhProvider {
    fn drop(&mut self) {
        // SAFETY: worker owns the query; CloseQuery also removes its counters.
        unsafe {
            PdhCloseQuery(self.query);
        }
    }
}
fn error(status: u32, operation: &str) -> String {
    format!("{operation}: PDH status 0x{status:08x}; counter/provider unavailable (no repair attempted)")
}
fn check(status: u32, operation: &str) -> Result<(), String> {
    if status == 0 {
        Ok(())
    } else {
        Err(error(status, operation))
    }
}

fn decode(buffer: &[u64], bytes: usize, count: usize) -> CounterResult {
    let capacity = std::mem::size_of_val(buffer);
    let item_bytes = count
        .checked_mul(size_of::<FormattedItem>())
        .ok_or("GPU counter item size overflow")?;
    if bytes > capacity || count > MAX_INSTANCES as usize || item_bytes > bytes {
        return Err("GPU counter returned invalid buffer dimensions".into());
    }
    let base = buffer.as_ptr() as usize;
    let mut rows = Vec::with_capacity(count);
    for index in 0..count {
        // SAFETY: validated item range lies within the aligned live allocation.
        let item = unsafe { buffer.as_ptr().cast::<FormattedItem>().add(index).read() };
        let start = item.name as usize;
        let offset = start
            .checked_sub(base)
            .ok_or("GPU counter name points outside its buffer")?;
        if offset < item_bytes
            || offset >= bytes
            || !start.is_multiple_of(std::mem::align_of::<u16>())
        {
            return Err("GPU counter name points outside its string area".into());
        }
        let max_units = ((bytes - offset) / size_of::<u16>()).min(512);
        // SAFETY: verified pointer and bounded length are inside the allocation.
        let name = unsafe { std::slice::from_raw_parts(item.name, max_units) };
        let end = name
            .iter()
            .position(|unit| *unit == 0)
            .ok_or("GPU counter instance name is unterminated or oversized")?;
        let name = String::from_utf16(&name[..end])
            .map_err(|_| "GPU counter instance name is not UTF-16")?;
        let value = if item.value.status == 0 || item.value.status == 1 {
            // SAFETY: PDH_FMT_DOUBLE selects this member; status validated above.
            let value = unsafe { item.value.number.double_value };
            if value.is_finite() && value >= 0.0 {
                Ok(value)
            } else {
                Err("counter returned invalid numeric data".into())
            }
        } else {
            Err(error(item.value.status, "GPU counter value"))
        };
        rows.push(CounterValue { name, value });
    }
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn buffer(name: &[u16], value: f64, status: u32) -> (Vec<u64>, usize) {
        let bytes = size_of::<FormattedItem>() + std::mem::size_of_val(name);
        let mut buffer = vec![0_u64; bytes.div_ceil(8)];
        let text = unsafe {
            buffer
                .as_mut_ptr()
                .cast::<u8>()
                .add(size_of::<FormattedItem>())
                .cast::<u16>()
        };
        unsafe {
            ptr::copy_nonoverlapping(name.as_ptr(), text, name.len());
            buffer
                .as_mut_ptr()
                .cast::<FormattedItem>()
                .write(FormattedItem {
                    name: text,
                    value: FormattedValue {
                        status,
                        number: FormattedNumber {
                            double_value: value,
                        },
                    },
                });
        }
        (buffer, bytes)
    }
    #[cfg(target_pointer_width = "64")]
    #[test]
    fn pdh_x64_abi_layout_matches_the_windows_header() {
        assert_eq!(size_of::<FormattedNumber>(), 8);
        assert_eq!(size_of::<FormattedValue>(), 16);
        assert_eq!(size_of::<FormattedItem>(), 24);
        assert_eq!(std::mem::offset_of!(FormattedValue, number), 8);
        assert_eq!(std::mem::offset_of!(FormattedItem, value), 8);
    }
    #[test]
    fn native_array_decodes_multiple_items_with_independent_status() {
        let first: Vec<u16> = "first\0".encode_utf16().collect();
        let second: Vec<u16> = "second\0".encode_utf16().collect();
        let header_bytes = 2 * size_of::<FormattedItem>();
        let bytes = header_bytes + 2 * (first.len() + second.len());
        let mut data = vec![0_u64; bytes.div_ceil(8)];
        unsafe {
            let start = data
                .as_mut_ptr()
                .cast::<u8>()
                .add(header_bytes)
                .cast::<u16>();
            ptr::copy_nonoverlapping(first.as_ptr(), start, first.len());
            ptr::copy_nonoverlapping(second.as_ptr(), start.add(first.len()), second.len());
            let items = data.as_mut_ptr().cast::<FormattedItem>();
            items.write(FormattedItem {
                name: start,
                value: FormattedValue {
                    status: 0,
                    number: FormattedNumber {
                        double_value: 1234.0,
                    },
                },
            });
            items.add(1).write(FormattedItem {
                name: start.add(first.len()),
                value: FormattedValue {
                    status: 1,
                    number: FormattedNumber { double_value: 0.0 },
                },
            });
        }
        let rows = decode(&data, bytes, 2).unwrap();
        assert_eq!(rows[0].name, "first");
        assert_eq!(rows[0].value, Ok(1234.0));
        assert_eq!(rows[1].name, "second");
        assert_eq!(rows[1].value, Ok(0.0));
    }
    #[test]
    fn native_formatted_values_validate_status_and_keep_true_zero() {
        let name = "pid_7_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D\0"
            .encode_utf16()
            .collect::<Vec<_>>();
        let (data, bytes) = buffer(&name, 0.0, 0);
        assert_eq!(decode(&data, bytes, 1).unwrap()[0].value, Ok(0.0));
        let (data, bytes) = buffer(&name, 42.0, 0xc000_0bba);
        assert!(decode(&data, bytes, 1).unwrap()[0].value.is_err());
        let (data, bytes) = buffer(&name, f64::NAN, 1);
        assert!(decode(&data, bytes, 1).unwrap()[0].value.is_err());
    }
    #[test]
    fn native_array_rejects_dimensions_names_and_outside_pointers() {
        let (mut data, bytes) = buffer(&[65, 0], 1.0, 0);
        assert!(decode(&data, bytes, 2).is_err());
        assert!(decode(&data, std::mem::size_of_val(data.as_slice()) + 1, 1).is_err());
        unsafe {
            (*data.as_mut_ptr().cast::<FormattedItem>()).name = ptr::null();
        }
        assert!(decode(&data, bytes, 1).is_err());
        let (data, bytes) = buffer(&[65, 66], 1.0, 0);
        assert!(decode(&data, bytes, 1).is_err());
        let (data, bytes) = buffer(&[0xd800, 0], 1.0, 0);
        assert!(decode(&data, bytes, 1).is_err());
    }
}
