use rust_duty_launcher::{
    download::{self, Control},
    install::{Installed, Store},
    manifest::Trust,
    source::Source,
    Error, Result, TARGET,
};
use std::{
    io::{self, BufRead},
    path::PathBuf,
    process::Child,
    sync::mpsc,
    thread,
    time::Duration,
};

fn default_root() -> Result<PathBuf> {
    if let Some(root) = std::env::var_os("LOCALAPPDATA") {
        return Ok(PathBuf::from(root).join("RustDuty"));
    }
    if let Some(root) = std::env::var_os("XDG_DATA_HOME") {
        return Ok(PathBuf::from(root).join("rust-duty"));
    }
    std::env::var_os("HOME")
        .map(|s| PathBuf::from(s).join(".local/share/rust-duty"))
        .ok_or_else(|| {
            rust_duty_launcher::invalid(
                "cannot determine a user-writable install directory; use --root PATH",
            )
        })
}
fn usage() {
    println!(
        "Rust Duty launcher\n\
Usage: rust-duty-launcher [--root PATH] [COMMAND] [-- GAME_ARGS]\n\
  open            Default: start installed game once; check/download in background\n\
  run             Manual interactive launcher; check/download once on startup\n\
  play            Start installed game and check/download in background\n\
  config          Show saved persistent settings/private-asset mappings\n\
  configure       Save mappings: --settings=PATH --weapon-asset=PATH --arms-asset=PATH\n\
                  --game-arg=ARG --clear-game-args --clear-settings --clear-weapon-asset --clear-arms-asset\n\
  status          Show installed version and persistent transfer progress\n\
  pause           Save progress and pause the active transfer\n\
  resume          Continue the existing transfer; start launcher if needed\n\
  cancel          Cancel and discard partial transfer; keep installed game\n\
  update          Check/download/stage/activate once, then exit\n\
  rollback        Return to retained last-good version while game is closed\n\
  recover --game-closed   Recover after abnormal launcher termination\n\
  install-local BUNDLE VERSION ENTRYPOINT   Explicit one-time offline install\n\
  help            Show this help\n\
Interactive controls: status, pause, resume, cancel, play, rollback, quit\n\
Production updates need a reviewed build with a pinned public key and signed\n\
assets in RHS059/rust_duty GitHub Releases. Trust is UNCONFIGURED by default.\n\
No service, scheduled polling, elevation, game termination or settings overwrite."
    );
}
fn status(store: &Store) -> Result<()> {
    let state = store.state()?;
    println!("Install: {}", store.root.display());
    println!(
        "Active: {}",
        state
            .active
            .map(|v| v.version.to_string())
            .unwrap_or_else(|| "not installed".into())
    );
    println!(
        "Control: {:?}; game pending: {}",
        download::control(&store.root)?,
        state.pending_launch
    );
    let path = store.root.join("status.json");
    if path.exists() {
        let progress: download::Progress = rust_duty_launcher::read_json(&path)?;
        println!(
            "{}: {} / {} bytes; {}",
            progress.phase, progress.bytes, progress.total, progress.message
        );
    }
    println!(
        "Signing trust: {}",
        if Trust::production().is_ok() {
            "configured"
        } else {
            "UNCONFIGURED"
        }
    );
    Ok(())
}
fn update(store: &Store) -> Result<Installed> {
    match download::control(&store.root)? {
        Control::Paused => return Err(Error::Paused),
        Control::Cancelled => return Err(Error::Cancelled),
        Control::Running => (),
    }
    let trust = Trust::production()?;
    let source = Source::github()?;
    download::report(
        &store.root,
        "checking",
        None,
        0,
        "Checking the signed GitHub release channel",
    )?;
    let manifest = store.check(&source, &trust, TARGET)?;
    store.stage(&source, &manifest)
}
fn update_thread(store: Store, result: mpsc::Sender<Result<Installed>>) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let update = update(&store);
        if let Err(e) = &update {
            let phase = match e {
                Error::Paused => "paused",
                Error::Cancelled => "cancelled",
                Error::Network(_) => "stalled",
                _ => "idle",
            };
            // Keep byte counts from the last durable checkpoint when reporting a stalled transfer.
            let previous = rust_duty_launcher::read_json::<download::Progress>(
                &store.root.join("status.json"),
            )
            .ok();
            let progress = download::Progress {
                phase: phase.into(),
                asset: previous.as_ref().and_then(|p| p.asset.clone()),
                bytes: previous.as_ref().map_or(0, |p| p.bytes),
                total: previous.map_or(0, |p| p.total),
                message: e.to_string(),
            };
            let _ = rust_duty_launcher::atomic_json(&store.root.join("status.json"), &progress);
        }
        let _ = result.send(update);
    })
}
fn run(store: &Store, auto_play: bool, game_args: Vec<String>) -> Result<()> {
    store.recover()?;
    println!("Rust Duty launcher. Type status, pause, resume, cancel, play, rollback, or quit.");
    println!("Install directory: {}", store.root.display());
    let (input_tx, input_rx) = mpsc::channel();
    thread::spawn(move || {
        for line in io::stdin().lock().lines() {
            match line {
                Ok(line) => {
                    if input_tx.send(line).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = input_tx.send("quit".into());
    });
    let (result_tx, result_rx) = mpsc::channel();
    let mut worker = Some(update_thread(store.clone(), result_tx.clone()));
    let mut child: Option<Child> = None;
    let mut automatic = rust_duty_launcher::launch::AutoPlayOnce::new(auto_play);
    if automatic.take_if_installed(store.state()?.active.is_some()) {
        match store.launch(&game_args) {
            Ok(game) => child = Some(game),
            Err(e) => eprintln!("Play: {e}"),
        }
    } else if auto_play {
        println!("No game installed yet. The first verified download will launch once when ready; an unconfigured launcher needs the one-time local install first.");
    }
    let mut pending = None;
    let mut quitting = false;
    let mut last_control = download::control(&store.root)?;
    loop {
        if let Ok(result) = result_rx.try_recv() {
            if let Some(handle) = worker.take() {
                let _ = handle.join();
            }
            match result {
                Ok(installed) => {
                    println!("Version {} is ready", installed.version);
                    pending = Some(installed);
                }
                Err(e) => {
                    let interrupted = matches!(e, Error::Paused | Error::Cancelled);
                    eprintln!("Update: {e}");
                    // A quick pause/resume can arrive while the old worker is finishing.
                    if interrupted
                        && download::control(&store.root)? == Control::Running
                        && !quitting
                    {
                        worker = Some(update_thread(store.clone(), result_tx.clone()));
                    }
                }
            }
        }
        if let Some(game) = child.as_mut() {
            if let Some(exit) = game.try_wait()? {
                child = None;
                store.finish_launch(exit.success())?;
                println!(
                    "Game exited ({exit}){}",
                    if exit.success() {
                        ""
                    } else {
                        "; restored last-good version when available"
                    }
                );
            }
        }
        let current = download::control(&store.root)?;
        if current == Control::Running
            && last_control != Control::Running
            && worker.is_none()
            && !quitting
        {
            worker = Some(update_thread(store.clone(), result_tx.clone()));
        }
        last_control = current;
        if current == Control::Cancelled {
            pending = None;
        }
        if child.is_none() && current == Control::Running && !quitting {
            if let Some(installed) = pending.take() {
                store.activate(installed)?;
                println!("Update activated; old version retained for rollback");
            }
        }
        if !quitting
            && child.is_none()
            && automatic.take_if_installed(store.state()?.active.is_some())
        {
            match store.launch(&game_args) {
                Ok(game) => child = Some(game),
                Err(e) => eprintln!("Play: {e}"),
            }
        }
        if quitting && child.is_none() && worker.is_none() {
            break;
        }
        match input_rx.recv_timeout(Duration::from_millis(200)) {
            Ok(line) => match line.trim() {
                "status" => status(store)?,
                "pause" => download::set_control(&store.root, Control::Paused)?,
                "resume" => {
                    download::set_control(&store.root, Control::Running)?;
                    if worker.is_none() && !quitting {
                        worker = Some(update_thread(store.clone(), result_tx.clone()));
                    }
                    last_control = Control::Running;
                }
                "cancel" => {
                    download::set_control(&store.root, Control::Cancelled)?;
                    pending = None;
                    if worker.is_none() {
                        download::cancel_partial(&store.root)?;
                    }
                }
                "play" if child.is_none() && !quitting => {
                    automatic.cancel();
                    match store.launch(&game_args) {
                        Ok(game) => child = Some(game),
                        Err(e) => eprintln!("Play: {e}"),
                    }
                }
                "play" => println!("The game is already running or the launcher is closing"),
                "rollback" if child.is_none() && worker.is_none() => match store.rollback() {
                    Ok(()) => println!("Restored last-good version"),
                    Err(e) => eprintln!("Rollback: {e}"),
                },
                "rollback" => println!("Close the game and pause the transfer before rollback"),
                "quit" | "exit" => {
                    if quitting {
                        continue;
                    }
                    quitting = true;
                    if worker.is_some() {
                        download::set_control(&store.root, Control::Paused)?;
                    }
                    if child.is_some() {
                        println!(
                            "Waiting for the game to exit; the launcher will not terminate it"
                        );
                    }
                }
                "" => (),
                _ => println!("Commands: status, pause, resume, cancel, play, rollback, quit"),
            },
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                thread::sleep(Duration::from_millis(200));
            }
            Err(mpsc::RecvTimeoutError::Timeout) => (),
        }
    }
    Ok(())
}
fn main_result() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let game_args = if let Some(index) = args.iter().position(|s| s == "--") {
        let rest = args.split_off(index + 1);
        args.pop();
        rest
    } else {
        vec![]
    };
    let mut root = default_root()?;
    if args.first().is_some_and(|s| s == "--root") {
        if args.len() < 2 {
            return Err(rust_duty_launcher::invalid("--root needs a path"));
        }
        root = PathBuf::from(args.remove(1));
        args.remove(0);
    }
    let command = args.first().map(String::as_str).unwrap_or("open");
    if matches!(command, "help" | "--help" | "-h") {
        usage();
        return Ok(());
    }
    if command == "trust-status" {
        match Trust::production() {
            Ok(_) => println!(
                "CONFIGURED {}",
                option_env!("RUST_DUTY_UPDATE_PUBLIC_KEY").ok_or(Error::Unconfigured)?
            ),
            Err(Error::Unconfigured) => println!("UNCONFIGURED"),
            Err(error) => return Err(error),
        }
        return Ok(());
    }
    let store = Store::open(&root)?;
    match command {
        "status" => return status(&store),
        "config" => {
            println!(
                "{}",
                serde_json::to_string_pretty(&rust_duty_launcher::launch::load(&store.root)?)?
            );
            return Ok(());
        }
        "pause" => return download::set_control(&store.root, Control::Paused),
        "cancel" => {
            download::set_control(&store.root, Control::Cancelled)?;
            if let Ok(_lock) = store.lock() {
                download::cancel_partial(&store.root)?;
            }
            return Ok(());
        }
        "resume" => {
            download::set_control(&store.root, Control::Running)?;
            let Ok(_lock) = store.lock() else {
                println!("Resume requested from the running launcher");
                return Ok(());
            };
            return run(&store, false, game_args);
        }
        _ => (),
    }
    let _lock = store.lock()?;
    match command {
        "open" | "run" | "play" => run(&store, command != "run", game_args),
        "update" => {
            store.recover()?;
            let ready = update(&store)?;
            store.activate(ready)
        }
        "rollback" => store.rollback(),
        "configure" => {
            let mut config = rust_duty_launcher::launch::load(&store.root)?;
            for option in &args[1..] {
                if let Some(path) = option.strip_prefix("--settings=") {
                    config.settings = Some(path.into());
                } else if let Some(path) = option.strip_prefix("--weapon-asset=") {
                    config.weapon_asset = Some(path.into());
                } else if let Some(path) = option.strip_prefix("--arms-asset=") {
                    config.arms_asset = Some(path.into());
                } else if let Some(arg) = option.strip_prefix("--game-arg=") {
                    config.game_args.push(arg.into());
                } else if option == "--clear-settings" {
                    config.settings = None;
                } else if option == "--clear-weapon-asset" {
                    config.weapon_asset = None;
                } else if option == "--clear-arms-asset" {
                    config.arms_asset = None;
                } else if option == "--clear-game-args" {
                    config.game_args.clear();
                } else {
                    return Err(rust_duty_launcher::invalid(format!(
                        "unknown launch configuration option: {option}"
                    )));
                }
            }
            rust_duty_launcher::launch::save(&store.root, &config)?;
            println!("Saved persistent launch mappings. Relative paths resolve from {} and are passed to the game as absolute paths.", store.root.display());
            Ok(())
        }
        "recover" if args.get(1).is_some_and(|a| a == "--game-closed") => {
            store.finish_launch(false)
        }
        "install-local" if args.len() == 4 => {
            let version = args[2]
                .parse()
                .map_err(|_| rust_duty_launcher::invalid("invalid stable version"))?;
            store.install_local(&PathBuf::from(&args[1]), version, &args[3])?;
            println!("Initial local bundle installed. It was explicitly trusted locally; network updates remain signature-gated.");
            Ok(())
        }
        _ => {
            usage();
            Err(rust_duty_launcher::invalid(
                "unknown command or missing arguments",
            ))
        }
    }
}
fn main() {
    if let Err(e) = main_result() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
