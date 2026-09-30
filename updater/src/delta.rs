//! RDDLT001: old size, new size, then COPY(offset,length) or ADD(length,bytes), END.
//! All integers are little endian u64. No compression, paths, or executable instructions.
use crate::{invalid, Result, MAX_ASSET};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};
pub const MAGIC: &[u8; 8] = b"RDDLT001";
fn number(reader: &mut impl Read) -> Result<u64> {
    let mut b = [0; 8];
    reader.read_exact(&mut b)?;
    Ok(u64::from_le_bytes(b))
}
pub fn apply(base: &Path, patch: &Path, output: &Path, expected_size: u64) -> Result<()> {
    let mut base = File::open(base)?;
    let mut patch = File::open(patch)?;
    let mut magic = [0; 8];
    patch.read_exact(&mut magic)?;
    if &magic != MAGIC {
        return Err(invalid("invalid delta magic"));
    }
    let old_size = number(&mut patch)?;
    let new_size = number(&mut patch)?;
    if old_size != base.metadata()?.len() || new_size != expected_size || new_size > MAX_ASSET {
        return Err(invalid("delta size mismatch"));
    }
    let mut output = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?;
    let mut written = 0u64;
    let mut buffer = [0; 65536];
    let mut operations = 0u64;
    loop {
        let mut tag = [0];
        patch.read_exact(&mut tag)?;
        if tag[0] == 255 {
            break;
        }
        operations += 1;
        if operations > 4_000_000 {
            return Err(invalid("too many delta operations"));
        }
        let offset = if tag[0] == 0 { number(&mut patch)? } else { 0 };
        let size = number(&mut patch)?;
        if size == 0 || written.checked_add(size).is_none_or(|n| n > new_size) {
            return Err(invalid("delta output overflow"));
        }
        match tag[0] {
            0 => {
                if offset.checked_add(size).is_none_or(|n| n > old_size) {
                    return Err(invalid("delta copy outside base"));
                }
                base.seek(SeekFrom::Start(offset))?;
                copy_exact(&mut base, &mut output, size, &mut buffer)?;
            }
            1 => copy_exact(&mut patch, &mut output, size, &mut buffer)?,
            _ => return Err(invalid("unknown delta operation")),
        }
        written += size;
    }
    let mut extra = [0];
    if written != new_size || patch.read(&mut extra)? != 0 {
        return Err(invalid("truncated output or trailing delta bytes"));
    }
    output.sync_all()?;
    Ok(())
}
pub(crate) fn copy_exact(
    from: &mut impl Read,
    to: &mut impl Write,
    mut len: u64,
    buf: &mut [u8],
) -> Result<()> {
    while len > 0 {
        let n = (len as usize).min(buf.len());
        from.read_exact(&mut buf[..n])?;
        to.write_all(&buf[..n])?;
        len -= n as u64;
    }
    Ok(())
}
