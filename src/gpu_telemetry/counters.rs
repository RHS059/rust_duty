use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Debug, Clone)]
pub(super) struct CounterValue {
    pub(super) name: String,
    pub(super) value: Result<f64, String>,
}
pub(super) type CounterResult = Result<Vec<CounterValue>, String>;
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Instance {
    pub(super) pid: Option<u32>,
    pub(super) adapter: String,
    pub(super) engine: Option<(u32, String)>,
}

/// Parse only the documented Windows GPU counter shape. Full instance names
/// (which include other applications' PIDs) are not retained in the export.
pub(super) fn instance(name: &str) -> Option<Instance> {
    let (pid, rest) = if let Some(rest) = name.strip_prefix("pid_") {
        let (pid, rest) = rest.split_once('_')?;
        (Some(pid.parse().ok()?), rest)
    } else {
        (None, name)
    };
    let parts: Vec<_> = rest.split('_').collect();
    if parts.len() < 5 || parts[0] != "luid" || parts[3] != "phys" {
        return None;
    }
    for hex in [&parts[1], &parts[2]] {
        let hex = hex.strip_prefix("0x")?;
        if hex.len() != 8 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return None;
        }
    }
    let physical: u32 = parts[4].parse().ok()?;
    let adapter = format!(
        "luid_{}_{}_phys_{physical}",
        parts[1].to_ascii_lowercase(),
        parts[2].to_ascii_lowercase()
    );
    let engine = if parts.len() == 5 {
        None
    } else {
        if parts.len() < 9 || parts[5] != "eng" || parts[7] != "engtype" {
            return None;
        }
        let kind = parts[8..].join("_");
        if kind.is_empty()
            || kind.len() > 64
            || !kind.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
        {
            return None;
        }
        Some((parts[6].parse().ok()?, kind))
    };
    Some(Instance {
        pid,
        adapter,
        engine,
    })
}
fn metric(value: Result<f64, String>) -> Value {
    match value {
        Ok(value) if value.is_finite() && value >= 0.0 => {
            json!({"value":value,"unavailable_reason":null})
        }
        Ok(_) => {
            json!({"value":null,"unavailable_reason":"counter returned a non-finite or negative value"})
        }
        Err(error) => json!({"value":null,"unavailable_reason":error}),
    }
}

pub(super) fn aggregate(
    engines: CounterResult,
    process_dedicated: CounterResult,
    process_shared: CounterResult,
    adapter_dedicated: CounterResult,
    adapter_shared: CounterResult,
    pid: u32,
) -> Value {
    let mut adapters = BTreeSet::new();
    let counters = [
        &engines,
        &process_dedicated,
        &process_shared,
        &adapter_dedicated,
        &adapter_shared,
    ];
    let mut rejected = 0;
    for rows in counters.iter().filter_map(|result| result.as_ref().ok()) {
        for row in rows {
            if let Some(parsed) = instance(&row.name) {
                adapters.insert(parsed.adapter);
            } else {
                rejected += 1;
            }
        }
    }
    let statuses: Vec<_> = counters
        .iter()
        .map(|result| match result {
            Ok(rows) => json!({"state":"queried","instance_count":rows.len()}),
            Err(error) => json!({"state":"unavailable","reason":error}),
        })
        .collect();
    let rows: Vec<_> = adapters
        .into_iter()
        .map(|adapter| {
            let whole = engine_values(&engines, &adapter, None);
            let process = engine_values(&engines, &adapter, Some(pid));
            json!({"adapter_id":adapter,"renderer_binding":"unverified",
            "adapter_busiest_engine_pct":metric(busiest(&whole)),
            "process_busiest_engine_pct":metric(busiest(&process)),
            "adapter_engines":engine_json(whole),"process_engines":engine_json(process),
            "process_dedicated_bytes":metric(memory(&process_dedicated,&adapter,Some(pid))),
            "process_shared_bytes":metric(memory(&process_shared,&adapter,Some(pid))),
            "adapter_dedicated_bytes":metric(memory(&adapter_dedicated,&adapter,None)),
            "adapter_shared_bytes":metric(memory(&adapter_shared,&adapter,None))})
        })
        .collect();
    json!({"adapters":rows,"counter_status":{"engine":statuses[0],"process_dedicated":statuses[1],
        "process_shared":statuses[2],"adapter_dedicated":statuses[3],"adapter_shared":statuses[4]},
        "rejected_instance_names":rejected,
        "unavailable_reason":if rows.is_empty(){Some("no recognized GPU adapter instances; counters may be unsupported, unavailable, or warming up")}else{None}})
}

type Engines = Result<BTreeMap<(u32, String), Result<f64, String>>, String>;
fn engine_values(result: &CounterResult, adapter: &str, pid: Option<u32>) -> Engines {
    let rows = result.as_ref().map_err(Clone::clone)?;
    let mut output: BTreeMap<(u32, String), Result<f64, String>> = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for row in rows {
        let parsed = instance(&row.name)
            .ok_or("unrecognized GPU engine instance; refusing a partial aggregate")?;
        if parsed.adapter != adapter
            || parsed.pid.is_none()
            || pid.is_some_and(|pid| parsed.pid != Some(pid))
        {
            continue;
        }
        let Some(engine) = parsed.engine.clone() else {
            continue;
        };
        let value = output.entry(engine).or_insert(Ok(0.0));
        if !seen.insert(parsed) {
            *value = Err("duplicate process/adapter/engine instance".into());
            continue;
        }
        match (&mut *value, &row.value) {
            (Ok(sum), Ok(next)) if next.is_finite() && (0.0..=100.0).contains(next) => *sum += next,
            (_, Err(error)) => *value = Err(error.clone()),
            (_, Ok(next)) if !next.is_finite() || !(0.0..=100.0).contains(next) => {
                *value = Err("invalid engine percentage".into())
            }
            _ => {}
        }
    }
    if output.is_empty() {
        Err("no matching validly named engine instances; absence is not zero utilization".into())
    } else {
        Ok(output)
    }
}
fn busiest(engines: &Engines) -> Result<f64, String> {
    let engines = engines.as_ref().map_err(Clone::clone)?;
    let mut max = 0.0_f64;
    for value in engines.values() {
        max = max.max(*value.as_ref().map_err(Clone::clone)?);
    }
    Ok(max.min(100.0))
}
fn engine_json(engines: Engines) -> Value {
    match engines {
        Ok(engines) => Value::Array(engines.into_iter().map(|((id,kind),value)| {
            let capped = value.as_ref().is_ok_and(|value| *value > 100.0);
            json!({"engine_id":id,"engine_type":kind,"utilization_pct":metric(value.map(|value| value.min(100.0))),
                "sum_capped_at_100":capped})
        }).collect()),
        Err(error) => json!({"unavailable_reason":error}),
    }
}
fn memory(result: &CounterResult, adapter: &str, pid: Option<u32>) -> Result<f64, String> {
    let rows = result.as_ref().map_err(Clone::clone)?;
    let values: Vec<_> = rows
        .iter()
        .filter(|row| {
            instance(&row.name).is_some_and(|parsed| {
                parsed.adapter == adapter && parsed.pid == pid && parsed.engine.is_none()
            })
        })
        .collect();
    match values.as_slice() {
        [value] => value.value.clone().and_then(|number| {
            if number.is_finite() && number >= 0.0 {
                Ok(number)
            } else {
                Err("invalid memory usage value".into())
            }
        }),
        [] => Err("no matching memory instance; absence is not zero bytes".into()),
        _ => Err("duplicate adapter memory instances".into()),
    }
}
