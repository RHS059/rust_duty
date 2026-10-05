use crate::action::ActionTuning;
use std::{fs, path::Path};

#[derive(Debug, Clone, PartialEq)]
pub struct Settings {
    pub sensitivity: f32,
    pub fov: f32,
    /// Camera-space viewmodel offset in meters. Positive X is right, positive Y is up.
    pub viewmodel_x: f32,
    /// Camera-space viewmodel offset in meters. Positive X is right, positive Y is up.
    pub viewmodel_y: f32,
    pub ads_fov: f32,
    pub walk_speed: f32,
    pub sprint_speed: f32,
    pub crouch_speed: f32,
    /// Fully aimed speed as a fraction of the selected stance's normal speed.
    pub ads_move_multiplier: f32,
    pub acceleration: f32,
    pub friction: f32,
    pub air_acceleration: f32,
    pub gravity: f32,
    pub jump_speed: f32,
    pub fire_rpm: f32,
    pub ads_time: f32,
    pub ads_out_time: f32,
    pub reload_credit: f32,
    pub empty_reload_time: f32,
    pub empty_reload_credit: f32,
    pub reload_time: f32,
    pub sprint_out_time: f32,
    pub hip_spread: f32,
    pub ads_spread: f32,
    pub recoil_pitch: f32,
    pub recoil_return: f32,
    /// Traversal, mount, obstruction and death tuning.
    pub action: ActionTuning,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            sensitivity: 0.10,
            fov: 90.,
            viewmodel_x: 0.,
            viewmodel_y: 0.,
            ads_fov: 65.,
            walk_speed: 4.826,
            sprint_speed: 7.239,
            crouch_speed: 3.1369,
            ads_move_multiplier: 0.5,
            acceleration: 9.,
            friction: 5.5,
            air_acceleration: 1.,
            gravity: 20.32,
            jump_speed: 6.345,
            fire_rpm: 666.6667,
            ads_time: 0.220,
            ads_out_time: 0.160,
            reload_credit: 1.350,
            empty_reload_time: 2.550,
            empty_reload_credit: 1.800,
            reload_time: 1.950,
            sprint_out_time: 0.20,
            hip_spread: 1.60,
            ads_spread: 0.08,
            recoil_pitch: 0.775,
            recoil_return: 21.,
            action: ActionTuning::default(),
        }
    }
}
impl Settings {
    /// Largest saved viewmodel offset on each axis, in meters.
    pub const VIEWMODEL_OFFSET_LIMIT: f32 = 0.20;
    /// One start-menu nudge, in meters.
    pub const VIEWMODEL_NUDGE: f32 = 0.005;

    /// Shift the saved viewmodel offset. X is right, Y is up. No forward/back.
    pub fn nudge_viewmodel(&mut self, x: f32, y: f32) {
        let limit = Self::VIEWMODEL_OFFSET_LIMIT;
        self.viewmodel_x = (self.viewmodel_x + x).clamp(-limit, limit);
        self.viewmodel_y = (self.viewmodel_y + y).clamp(-limit, limit);
    }

    /// Set the saved viewmodel offset. X is right, Y is up. Each axis clamps to +/- 0.20 m.
    pub fn set_viewmodel(&mut self, x: f32, y: f32) {
        let limit = Self::VIEWMODEL_OFFSET_LIMIT;
        if x.is_finite() {
            self.viewmodel_x = x.clamp(-limit, limit);
        }
        if y.is_finite() {
            self.viewmodel_y = y.clamp(-limit, limit);
        }
    }

    /// Published-data M4A1-inspired candidate, separate from the authored default.
    ///
    /// Timing targets are provisional 2009 multiplayer values without perks or
    /// attachments. Movement conversion, ADS exit, empty-reload credit, recoil,
    /// and spread include explicitly authored assumptions: see docs/M4_PROFILE.md.
    /// This settings choice does not select or depend on a visual weapon model.
    pub fn m4_candidate() -> Self {
        let base = Self::default();
        Self {
            fire_rpm: 60. / 0.070,
            ads_time: 0.250,
            ads_out_time: 0.250,
            reload_credit: 1.100,
            reload_time: 2.029,
            empty_reload_time: 2.359,
            // The separate empty ammunition-credit event is not established.
            empty_reload_credit: 1.800,
            sprint_out_time: 0.300,
            walk_speed: base.walk_speed * 0.95,
            sprint_speed: base.sprint_speed * 0.95,
            crouch_speed: base.crouch_speed * 0.95,
            // Published 0.38 and 0.95 refer to the same base: 0.38 / 0.95.
            ads_move_multiplier: 0.40,
            ..base
        }
    }

    pub fn load(path: impl AsRef<Path>) -> Self {
        Self::load_with_base(path, Self::default())
    }

    /// Apply a partial settings file to a selected profile. Missing files and
    /// unknown/invalid entries retain the base values; finite values are clamped.
    pub fn load_with_base(path: impl AsRef<Path>, mut s: Self) -> Self {
        if let Ok(text) = fs::read_to_string(path) {
            for line in text.lines() {
                let line = line.split('#').next().unwrap_or("").trim();
                if let Some((key, value)) = line.split_once('=') {
                    if let Ok(v) = value.trim().parse::<f32>() {
                        if !v.is_finite() {
                            continue;
                        }
                        let slot = match key.trim() {
                            "sensitivity" => Some((&mut s.sensitivity, 0.01, 1.)),
                            "fov" => Some((&mut s.fov, 65., 120.)),
                            "viewmodel_x" => Some((
                                &mut s.viewmodel_x,
                                -Self::VIEWMODEL_OFFSET_LIMIT,
                                Self::VIEWMODEL_OFFSET_LIMIT,
                            )),
                            "viewmodel_y" => Some((
                                &mut s.viewmodel_y,
                                -Self::VIEWMODEL_OFFSET_LIMIT,
                                Self::VIEWMODEL_OFFSET_LIMIT,
                            )),
                            "ads_fov" => Some((&mut s.ads_fov, 35., 100.)),
                            "walk_speed" => Some((&mut s.walk_speed, 1., 12.)),
                            "sprint_speed" => Some((&mut s.sprint_speed, 1., 18.)),
                            "crouch_speed" => Some((&mut s.crouch_speed, 0.5, 8.)),
                            "ads_move_multiplier" => Some((&mut s.ads_move_multiplier, 0., 1.)),
                            "acceleration" => Some((&mut s.acceleration, 1., 120.)),
                            "friction" => Some((&mut s.friction, 1., 40.)),
                            "air_acceleration" => Some((&mut s.air_acceleration, 0., 20.)),
                            "gravity" => Some((&mut s.gravity, 5., 50.)),
                            "jump_speed" => Some((&mut s.jump_speed, 1., 12.)),
                            "fire_rpm" => Some((&mut s.fire_rpm, 60., 1200.)),
                            "ads_time" => Some((&mut s.ads_time, 0.05, 1.)),
                            "ads_out_time" => Some((&mut s.ads_out_time, 0.05, 1.)),
                            "reload_credit" => Some((&mut s.reload_credit, 0.1, 8.)),
                            "empty_reload_time" => Some((&mut s.empty_reload_time, 0.2, 8.)),
                            "empty_reload_credit" => Some((&mut s.empty_reload_credit, 0.1, 8.)),
                            "reload_time" => Some((&mut s.reload_time, 0.2, 8.)),
                            "sprint_out_time" => Some((&mut s.sprint_out_time, 0., 1.)),
                            "hip_spread" => Some((&mut s.hip_spread, 0., 8.)),
                            "ads_spread" => Some((&mut s.ads_spread, 0., 3.)),
                            "recoil_pitch" => Some((&mut s.recoil_pitch, 0., 5.)),
                            "recoil_return" => Some((&mut s.recoil_return, 2., 30.)),
                            _ => None,
                        };
                        let handled = if let Some((slot, min, max)) = slot {
                            *slot = v.clamp(min, max);
                            true
                        } else {
                            false
                        };
                        if !handled {
                            if let Some((_, slot, min, max)) = s
                                .action
                                .fields_mut()
                                .into_iter()
                                .find(|(name, ..)| *name == key.trim())
                            {
                                *slot = v.clamp(min, max);
                            }
                        }
                    }
                }
            }
        }
        s.reload_credit = s.reload_credit.min(s.reload_time);
        s.empty_reload_credit = s.empty_reload_credit.min(s.empty_reload_time);
        s
    }
    pub fn save(&self, path: impl AsRef<Path>) -> std::io::Result<()> {
        let fields = [
            ("sensitivity", self.sensitivity),
            ("fov", self.fov),
            ("viewmodel_x", self.viewmodel_x),
            ("viewmodel_y", self.viewmodel_y),
            ("ads_fov", self.ads_fov),
            ("walk_speed", self.walk_speed),
            ("sprint_speed", self.sprint_speed),
            ("crouch_speed", self.crouch_speed),
            ("ads_move_multiplier", self.ads_move_multiplier),
            ("acceleration", self.acceleration),
            ("friction", self.friction),
            ("air_acceleration", self.air_acceleration),
            ("gravity", self.gravity),
            ("jump_speed", self.jump_speed),
            ("fire_rpm", self.fire_rpm),
            ("ads_time", self.ads_time),
            ("ads_out_time", self.ads_out_time),
            ("reload_credit", self.reload_credit),
            ("empty_reload_time", self.empty_reload_time),
            ("empty_reload_credit", self.empty_reload_credit),
            ("reload_time", self.reload_time),
            ("sprint_out_time", self.sprint_out_time),
            ("hip_spread", self.hip_spread),
            ("ads_spread", self.ads_spread),
            ("recoil_pitch", self.recoil_pitch),
            ("recoil_return", self.recoil_return),
        ];
        let mut out = String::from("# Vector Range tuning settings. F6 reloads, F5 saves.\n# Distances meters, times seconds, angles degrees. FOV is horizontal.\n# ADS movement is a fraction of normal stance speed.\n");
        for (key, value) in fields {
            out.push_str(&format!("{key} = {value:.4}\n"));
        }
        let mut action = self.action.clone();
        for (key, value, ..) in action.fields_mut() {
            out.push_str(&format!("{key} = {value:.4}\n"));
        }
        fs::write(path, out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn config_rejects_nonfinite_values_and_clamps_credit_to_ready() {
        let path = std::env::temp_dir().join(format!("vector-settings-{}.cfg", std::process::id()));
        fs::write(&path,"sensitivity = NaN\nfov = 999\nreload_time = 1\nreload_credit = 5\nempty_reload_time = 2\nempty_reload_credit = 6\nunknown = 17\n").unwrap();
        let s = Settings::load(&path);
        assert_eq!(s.sensitivity, 0.1);
        assert_eq!(s.fov, 120.);
        assert_eq!(s.reload_credit, 1.);
        assert_eq!(s.empty_reload_credit, 2.);
        s.save(&path).unwrap();
        let roundtrip = Settings::load(&path);
        assert_eq!(roundtrip.fov, s.fov);
        assert_eq!(roundtrip.reload_time, s.reload_time);
        assert_eq!(roundtrip.viewmodel_x, 0.);
        assert_eq!(roundtrip.viewmodel_y, 0.);
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn viewmodel_offset_clamps_and_roundtrips() {
        let path = std::env::temp_dir().join(format!(
            "vector-viewmodel-slider-{}.cfg",
            std::process::id()
        ));
        fs::write(
            &path,
            "viewmodel_x = 0.05\nviewmodel_y = 9\nviewmodel_x = NaN\n",
        )
        .unwrap();
        let loaded = Settings::load(&path);
        assert_eq!(loaded.viewmodel_x, 0.05);
        assert_eq!(loaded.viewmodel_y, Settings::VIEWMODEL_OFFSET_LIMIT);
        let mut set = Settings::default();
        set.set_viewmodel(1., -1.);
        assert_eq!(set.viewmodel_x, Settings::VIEWMODEL_OFFSET_LIMIT);
        assert_eq!(set.viewmodel_y, -Settings::VIEWMODEL_OFFSET_LIMIT);
        set.set_viewmodel(f32::NAN, 0.01);
        assert_eq!(set.viewmodel_x, Settings::VIEWMODEL_OFFSET_LIMIT);
        assert_eq!(set.viewmodel_y, 0.01);
        set.nudge_viewmodel(Settings::VIEWMODEL_NUDGE, -Settings::VIEWMODEL_NUDGE);
        assert_eq!(set.viewmodel_x, Settings::VIEWMODEL_OFFSET_LIMIT);
        assert_eq!(set.viewmodel_y, 0.01 - Settings::VIEWMODEL_NUDGE);
        loaded.save(&path).unwrap();
        let roundtrip = Settings::load(&path);
        assert_eq!(roundtrip.viewmodel_x, loaded.viewmodel_x);
        assert_eq!(roundtrip.viewmodel_y, loaded.viewmodel_y);
        fs::remove_file(path).unwrap();
    }
}
