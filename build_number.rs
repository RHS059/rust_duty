//! A CI build number identifies one workflow run attempt, shared by its platforms.
//! Release ordering deliberately remains the stable Cargo version.
use std::time::{SystemTime, UNIX_EPOCH};

fn positive(value: &str) -> Result<u64, &'static str> {
    if value.starts_with('0') || !value.bytes().all(|c| c.is_ascii_digit()) {
        return Err("build identity requires canonical positive integers");
    }
    value
        .parse()
        .map_err(|_| "invalid or oversized build identity")
}

pub fn ci_number(run: &str, attempt: &str) -> Result<String, &'static str> {
    Ok(format!("{}.{}", positive(run)?, positive(attempt)?))
}

pub fn current() -> String {
    match (
        std::env::var("GITHUB_RUN_ID"),
        std::env::var("GITHUB_RUN_ATTEMPT"),
    ) {
        (Ok(run), Ok(attempt)) => ci_number(&run, &attempt).expect("GitHub build identity"),
        (Err(_), Err(_)) => {
            assert!(
                std::env::var("GITHUB_ACTIONS").as_deref() != Ok("true"),
                "GitHub builds must provide run ID and attempt"
            );
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("local build clock")
                .as_nanos();
            format!("local.{nanos}.{}", std::process::id())
        }
        _ => panic!("partial GitHub build identity: both run ID and attempt are required"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reruns_and_independent_runs_have_different_numbers() {
        assert_ne!(ci_number("100", "1"), ci_number("100", "2"));
        assert_ne!(ci_number("100", "1"), ci_number("101", "1"));
        assert_eq!(ci_number("100", "1"), ci_number("100", "1"));
    }
    #[test]
    fn reject_missing_noncanonical_and_oversized_numbers() {
        for value in ["", "0", "01", "-1", "1.2", " 1", "18446744073709551616"] {
            assert!(ci_number(value, "1").is_err());
            assert!(ci_number("1", value).is_err());
        }
    }
}
