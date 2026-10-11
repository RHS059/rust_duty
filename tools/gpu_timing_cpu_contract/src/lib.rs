//! Compile the isolated helpers and run only their pure CPU unit tests.
//! No test creates an instance, adapter, device, surface, window or game.
#![deny(warnings)]

// These helpers are intentionally not integrated into the game yet. Only
// disconnected public-API dead code is exempted; other warnings remain errors.
#[allow(dead_code)]
#[path = "../../../src/render/gpu_timing.rs"]
mod gpu_timing;

#[allow(dead_code)]
#[path = "../../../src/render/present_policy.rs"]
mod present_policy;
