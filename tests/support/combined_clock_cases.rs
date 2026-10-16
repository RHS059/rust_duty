// Included inside authored_high_mantle::tests. Uses private test-only admission;
// production high-mantle pins remain closed and no payload assets are supplied.
fn combined_low_binding() -> crate::authored_low_vault::LowVaultBinding {
    let (vra, _, _) = payload_at_hz(false, 1., 64, 60);
    let receipt = serde_json::to_vec(&json!({
        "schema":"rust-duty-low-vault-runtime/v1",
        "presentation_policy":crate::authored_low_vault::POLICY,
        "clip_name":ACTION,"source_action":"original_combined_clock_fixture",
        "export_take":"synthetic_take","candidate_sha256":"1".repeat(64),
        "source_action_fingerprint":"2".repeat(64),"source_fbx_sha256":"3".repeat(64),
        "asset_vra_sha256":rust_duty_launcher::bytes_hash(&vra),
        "candidate_frame_range":[1,64],"reference_frame_range_half_open":[7284,7348],
        "native_fps":[60,1],"native_crop":[0,63],"imported_frame_offset":1,
        "subdivisions":1,"return_seconds":0.8,"actor_basis":"reload_mesh_local",
        "anchor_actor":ANCHOR
    })).unwrap();
    crate::authored_low_vault::LowVaultBinding::from_bytes(
        &vra, &receipt, &rust_duty_launcher::bytes_hash(&receipt), ACTION,
    ).unwrap()
}
fn combined_bind_both(sim: &mut Simulation) {
    sim.set_high_mantle_binding(Some(HighMantleBinding::synthetic(0.8)));
    sim.set_low_vault_binding(Some(combined_low_binding())).unwrap();
}
// Change only the synthetic collision setup/player start, retaining both clocks.
fn combined_next_obstacle(sim: &mut Simulation, high: bool) {
    let next = scene(if high { 1.8 } else { 0.6 }, false);
    sim.blocks = next.blocks;
    sim.player = next.player;
}
#[test]
fn combined_new_low_and_high_supersede_each_others_outgoing_tail() {
    for first_high in [false, true] {
        for completed in [false, true] {
            let mut sim = scene(if first_high { 1.8 } else { 0.6 }, false);
            combined_bind_both(&mut sim);
            tick(&mut sim, request());
            if completed {
                while sim.player.mantle.is_some() { tick(&mut sim, Input::default()); }
            } else {
                for _ in 0..20 { tick(&mut sim, Input::default()); }
                sim.cancel_mantle();
            }
            let old_low_generation = sim.low_vault_generation();
            if first_high { assert!(sim.high_mantle_presentation().unwrap().outgoing.is_some()); }
            combined_next_obstacle(&mut sim, !first_high);
            tick(&mut sim, request());
            assert_ne!(old_low_generation, sim.low_vault_generation());
            let state = sim.player.mantle.unwrap();
            if first_high {
                assert_eq!(state.kind, MantleKind::Low);
                assert!(sim.high_mantle_presentation().is_none());
                assert!(sim.low_vault_sample().is_some());
                assert!((sim.low_vault_sample().unwrap().source_frame - 1.5).abs() < 1e-6);
            } else {
                assert_eq!(state.kind, MantleKind::High);
                assert!(sim.low_vault_sample().is_none());
                let high = sim.high_mantle_presentation().unwrap();
                assert!(high.outgoing.is_none());
                assert!((high.sample.source_frame - 1.5).abs() < 1e-6);
            }
        }
    }
}
#[test]
fn combined_every_binding_combination_keeps_legacy_and_native_durations() {
    for low in [false, true] {
        for high in [false, true] {
            for high_path in [false, true] {
                let mut sim = scene(if high_path { 1.8 } else { 0.6 }, high);
                if low { sim.set_low_vault_binding(Some(combined_low_binding())).unwrap(); }
                let expected = if high_path {
                    if high { (190, NATIVE_SECONDS as f32) } else { (102, 0.85) }
                } else if low { (126, 63. / 60.) } else { (72, 0.60) };
                tick(&mut sim, request());
                assert_eq!(sim.player.mantle.unwrap().duration(), expected.1);
                let mut count = 1;
                while sim.player.mantle.is_some() {
                    tick(&mut sim, Input::default()); count += 1; assert!(count <= 190);
                }
                assert_eq!(count, expected.0);
                assert_eq!(sim.low_vault_sample().is_some(), low && !high_path);
                assert_eq!(sim.high_mantle_presentation().is_some(), high && high_path);
            }
        }
    }
}
#[test]
fn combined_death_reset_level_and_rebinding_invalidate_only_the_affected_clocks() {
    for high_path in [false, true] {
        for mode in 0..4 {
            let mut sim = scene(if high_path { 1.8 } else { 0.6 }, false);
            combined_bind_both(&mut sim);
            tick(&mut sim, request());
            let generation = sim.low_vault_generation();
            match mode {
                0 => sim.kill(),
                1 => sim.reset(),
                2 => sim.install_level(scene(0.6, false).blocks, vec3(0., 0., 1.), -std::f32::consts::FRAC_PI_2),
                _ => { sim.set_low_vault_binding(None).unwrap(); sim.set_high_mantle_binding(None); },
            }
            assert_ne!(sim.low_vault_generation(), generation);
            assert!(sim.low_vault_sample().is_none());
            assert!(sim.high_mantle_presentation().is_none());
            if mode != 3 {
                assert!(sim.low_vault_binding().is_some());
                assert!(sim.high_mantle_binding().is_some());
                assert!(sim.player.mantle.is_none());
            }
        }
    }
}
#[test]
fn combined_high_low_transition_trace_is_render_partition_invariant() {
    let mut baseline = None;
    for fps in [30, 60, 144, 240] {
        let mut sim = scene(1.8, false);
        combined_bind_both(&mut sim);
        let mut clock = crate::clock::FixedClock::default();
        let mut ticks = 0;
        let mut trace = Vec::new();
        for _ in 0..fps * 4 {
            let steps = clock.advance(1. / fps as f64).unwrap();
            for _ in 0..steps {
                if ticks == 200 { combined_next_obstacle(&mut sim, false); }
                tick(&mut sim, if ticks == 0 || ticks == 200 { request() } else { Input::default() });
                trace.push((sim.player.position, sim.low_vault_sample(), sim.high_mantle_presentation(), sim.low_vault_generation()));
                ticks += 1;
            }
            let before = (sim.time, sim.low_vault_sample(), sim.high_mantle_presentation());
            assert_eq!(before, (sim.time, sim.low_vault_sample(), sim.high_mantle_presentation()));
        }
        assert_eq!(ticks, 480);
        if let Some(expected) = &baseline { assert_eq!(&trace, expected, "{fps} FPS"); }
        else { baseline = Some(trace); }
    }
}
