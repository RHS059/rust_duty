//! Source-only binary32 arithmetic-domain supplement. This does not attest GPU execution.
use serde_json::{json, Value};
const U: f64 = 1.0 / 8_388_608.0;
const MAX: f64 = f32::MAX as f64;
#[derive(Clone, Copy, Debug)]
struct D {
    q: Option<i32>,
    magnitude: f64,
}
impl D {
    fn zero() -> Self {
        Self {
            q: None,
            magnitude: 0.,
        }
    }
    fn f32(x: f32) -> Self {
        assert!(x.is_finite());
        if x == 0. {
            return Self::zero();
        }
        let bits = x.to_bits() & 0x7fffffff;
        let exp = ((bits >> 23) & 255) as i32;
        let sig = (bits & 0x7fffff) | if exp != 0 { 1 << 23 } else { 0 };
        let q = if exp == 0 { -149 } else { exp - 127 - 23 } + sig.trailing_zeros() as i32;
        Self {
            q: Some(q),
            magnitude: f64::from(x).abs(),
        }
    }
    fn union(self, b: Self) -> Self {
        Self {
            q: match (self.q, b.q) {
                (Some(a), Some(b)) => Some(a.min(b)),
                (a, None) | (None, a) => a,
            },
            magnitude: self.magnitude.max(b.magnitude),
        }
    }
}
#[derive(Default)]
struct Check {
    count: u64,
    min_q: Option<i32>,
    max_mag: f64,
    failures: u64,
}
impl Check {
    fn observe(&mut self, x: D) -> D {
        self.count += 1;
        self.max_mag = self.max_mag.max(x.magnitude);
        if let Some(q) = x.q {
            self.min_q = Some(self.min_q.map_or(q, |a| a.min(q)));
            if q < -126 || !x.magnitude.is_finite() || x.magnitude >= MAX / (1. + U) {
                self.failures += 1;
            }
        }
        x
    }
    fn mul(&mut self, a: D, b: D) -> D {
        if a.q.is_none() || b.q.is_none() {
            return self.observe(D::zero());
        }
        let d = D {
            q: Some(a.q.unwrap() + b.q.unwrap()),
            magnitude: (a.magnitude * b.magnitude * (1. + U)).next_up(),
        };
        self.observe(d)
    }
    fn add(&mut self, a: D, b: D) -> D {
        let mut d = a.union(b);
        d.magnitude = ((a.magnitude + b.magnitude) * (1. + U)).next_up();
        if d.q.is_none() {
            d.magnitude = 0.;
        }
        self.observe(d)
    }
    fn dot(&mut self, a: [D; 4], b: [D; 4]) -> D {
        let products: Vec<D> = a.into_iter().zip(b).map(|(a, b)| self.mul(a, b)).collect();
        // Every partial-sum order has the same or coarser dyadic lattice. The sum of
        // all magnitudes bounds every subset, and three roundings bound every tree.
        let mut d = products.iter().copied().fold(D::zero(), D::union);
        d.magnitude =
            (products.iter().map(|d| d.magnitude).sum::<f64>() * (1. + U).powi(3)).next_up();
        if d.q.is_none() {
            d.magnitude = 0.;
        }
        self.observe(d)
    }
    fn mat(&mut self, a: [D; 16], b: [D; 16]) -> [D; 16] {
        std::array::from_fn(|n| {
            let r = n % 4;
            let c = n / 4;
            self.dot(
                std::array::from_fn(|k| a[k * 4 + r]),
                std::array::from_fn(|k| b[c * 4 + k]),
            )
        })
    }
    fn vec(&mut self, a: [D; 16], b: [D; 4]) -> [D; 4] {
        std::array::from_fn(|r| self.dot(std::array::from_fn(|k| a[k * 4 + r]), b))
    }
}
pub fn check(projection: [f32; 16], model: [f32; 16], positions: &[[f32; 3]], dx12: bool) -> Value {
    let mut c = Check::default();
    let p = projection.map(D::f32);
    let m = model.map(D::f32);
    let v = [0, 1, 2, 3].map(|axis| {
        if axis == 3 {
            D::f32(1.)
        } else {
            positions
                .iter()
                .map(|v| D::f32(v[axis]))
                .fold(D::zero(), D::union)
        }
    });
    for x in p.into_iter().chain(m).chain(v) {
        c.observe(x);
    }
    if dx12 {
        let r = [
            1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 0.5, 0., 0., 0., 0.5, 1.,
        ]
        .map(D::f32);
        let rp = c.mat(r, p);
        let rpm = c.mat(rp, m);
        c.vec(rpm, v);
    } else {
        let mv = c.vec(m, v);
        c.vec(p, mv);
        let pm = c.mat(p, m);
        c.vec(pm, v);
        // Fully distributed sixteen-term dot may form each p*m*v product first.
        for row in 0..4 {
            let mut sum = D::zero();
            for k in 0..4 {
                for j in 0..4 {
                    let a = c.mul(p[j * 4 + row], m[k * 4 + j]);
                    let b = c.mul(a, v[k]);
                    sum = c.add(sum, b);
                }
            }
        }
    }
    json!({"checked_abstract_nodes":c.count,"minimum_nonzero_dyadic_exponent":c.min_q,"maximum_rounded_magnitude_upper":c.max_mag,"unsupported_domain_nodes":c.failures,"normal_or_exact_zero_no_overflow":c.failures==0,"positions":positions.len(),"scope":"all source vertices of this mesh; every four-term sum ordering and contraction no worse than its expansion; current-host source replay, not native GPU observation"})
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dyadic_input_quantum() {
        assert_eq!(D::f32(1.).q, Some(0));
        assert_eq!(D::f32(0.5).q, Some(-1));
        assert_eq!(D::f32(f32::MIN_POSITIVE).q, Some(-126));
        assert_eq!(D::f32(f32::from_bits(1)).q, Some(-149));
        assert_eq!(D::f32(0.).q, None);
    }
    #[test]
    fn cancellation_preserves_lattice() {
        let mut c = Check::default();
        let a = D::f32(f32::from_bits(0x3f800001));
        let b = D::f32(-1.);
        let x = c.add(a, b);
        assert_eq!(x.q, Some(-23));
        assert_eq!(c.failures, 0);
    }
    #[test]
    fn subnormal_and_overflow_fail_closed() {
        let mut c = Check::default();
        c.mul(D::f32(f32::MIN_POSITIVE), D::f32(0.5));
        assert!(c.failures > 0);
        let mut c = Check::default();
        c.mul(D::f32(f32::MAX), D::f32(2.));
        assert!(c.failures > 0);
    }
    #[test]
    fn all_zero_is_exact_zero() {
        let mut c = Check::default();
        let x = c.dot([D::zero(); 4], [D::zero(); 4]);
        assert_eq!(x.q, None);
        assert_eq!(c.failures, 0);
    }
}
