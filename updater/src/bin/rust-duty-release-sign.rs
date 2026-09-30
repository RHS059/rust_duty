//! User-local release-owner helper. Never prints private key material.
use rust_duty_launcher::{invalid, signing, Result};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "help".into());
    if matches!(command.as_str(), "help" | "--help" | "-h") {
        println!(
            "Release-owner signing helper (not used by the game launcher).\n\
keygen --private-key ABS_PATH --public-key PATH --confirm-create-release-key\n\
public-key --private-key ABS_PATH [--output PATH]\n\
sign (--private-key ABS_PATH | --private-key-stdin) --payload PATH --signature PATH\n\
Key generation is only for the owner's personally confirmed local setup.\n\
Never generate a production key in chat, CI, a repository or a shared workspace.\n\
On Windows, use setup-release-signing.ps1 to protect the local directory first.\n\
Private key values are never accepted as arguments or printed. Outputs never overwrite files."
        );
        return Ok(());
    }
    let mut options = HashMap::new();
    let mut confirmed = false;
    let mut stdin = false;
    while let Some(option) = args.next() {
        match option.as_str() {
            "--confirm-create-release-key" => confirmed = true,
            "--private-key-stdin" => stdin = true,
            "--private-key" | "--public-key" | "--output" | "--payload" | "--signature" => {
                let value = args.next().ok_or_else(|| invalid("missing option value"))?;
                if options.insert(option, value).is_some() {
                    return Err(invalid("duplicate option"));
                }
            }
            _ => return Err(invalid("unrecognized signing-helper option")),
        }
    }
    let path = |name: &str| -> Result<PathBuf> {
        options
            .get(name)
            .map(PathBuf::from)
            .ok_or_else(|| invalid(format!("missing {name}")))
    };
    if command == "keygen" {
        if stdin {
            return Err(invalid("keygen does not accept private input"));
        }
        let private = path("--private-key")?;
        let public = path("--public-key")?;
        signing::generate_local(&private, &public, confirmed)?;
        println!("Created the local private key file and separate public key file. Private material was not printed. Keep the private file outside the repository and securely backed up.");
        return Ok(());
    }
    if !matches!(command.as_str(), "public-key" | "sign") {
        return Err(invalid("unknown signing-helper command"));
    }
    if stdin && options.contains_key("--private-key") {
        return Err(invalid("choose one private key input"));
    }
    let key = if stdin {
        signing::read_private(std::io::stdin().lock())?
    } else {
        signing::read_private_file(&path("--private-key")?)?
    };
    match command.as_str() {
        "public-key" => {
            if let Some(output) = options.get("--output") {
                signing::write_public(&key, Path::new(output))?;
            } else {
                println!("{}", signing::public_hex(&key));
            }
            Ok(())
        }
        "sign" => {
            signing::sign_manifest(&key, &path("--payload")?, &path("--signature")?)?;
            println!("Manifest signature written; private key material was not printed.");
            Ok(())
        }
        _ => Err(invalid("unknown signing-helper command")),
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Signing setup failed: {error}");
        std::process::exit(1);
    }
}
