# Porting findings — `autoware_ndt_scan_matcher` (C++ → Rust)

This ledger records **upstream bugs / behavioral divergences** discovered while porting
`autoware_ndt_scan_matcher` to Rust.

**Standing rule** (see `plan/ndt_in_rust.md` → "Upstream bug / divergence discovery"): on discovery,
**always notify the user** and **add an entry here**. The port **reproduces** the C++ behavior
verbatim (the differential test vs C++ is the oracle — it does *not* fix bugs locally); the correct
fix goes **upstream** (pcl/Autoware), and the port re-syncs only after upstream merges.

## Entry schema

- **Location (upstream):** `file:line`
- **Type:** bug / approximation / divergence
- **Evidence:** minimal proof (derivation / test)
- **Correct value:** what it should be
- **Impact:** on behavior / safety
- **Decision:** reproduce / fix — and why
- **Revisit trigger:** when to change the port
- **Upstream:** issue/PR link + status
- **Verification:** how the port pins / validates it

---

## ndt-hessian — pcl NDT angle-Hessian sign error (∂²T/∂pitch² x-component)

- **Location (upstream):** `src/ndt_omp/multigrid_ndt_omp_impl.hpp` ~line 599,
  `computeAngleDerivatives`, `h_ang_.row(6)` (the "d1" row).
- **Type:** bug — an isolated coefficient sign error. The NDT **gradient is exact**; only this one
  Hessian term is wrong.
- **Evidence:** Hand-derivation of `R = Rx(roll)·Ry(pitch)·Rz(yaw)` applied to a point `x`:
  ```
  (R x)_x  = cy·cz·x0 − cy·sz·x1 + sy·x2
  ∂/∂pitch = −sy·cz·x0 + sy·sz·x1 + cy·x2
  ∂²/∂pitch² = −cy·cz·x0 + cy·sz·x1 − sy·x2          ⟹  d1 = (−cy·cz,  cy·sz,  −sy)
  ```
  Cross-checked with the same method: rows 0,1 (roll²), 7,8 (pitch² y/z components), and 12–14
  (yaw²) **all match C++ exactly** — so the error is isolated to `d1`'s 3rd entry (`+sy`, should be
  `−sy`). The Rust port's finite-difference tests independently confirm the gradient is exact while
  the analytic Hessian (pcl form) disagrees with FD on the angle-angle block.
- **Correct value (upstream fix):**
  ```cpp
  h_ang_.row(6) << (-cy * cz), (cy * sz), (-sy), 0.0f;   // d1   (change (sy) -> (-sy))
  ```
- **Impact:** affects only the pitch² term of the Hessian → the Newton search **direction**, not the
  optimum. The gradient is exact, so the stationary point (`g = 0`) is unchanged; the *returned* pose
  can differ within the convergence tolerance because the loop halts on the H-dependent step norm
  (to be quantified at E4d). This is the behavior pcl/Autoware has shipped for years — it is **not a
  port-introduced risk**.
- **Decision:** **reproduce `+sy` verbatim** in the Rust port. "Fixing" it would make the port
  diverge from the C++ engine and break the differential-testing oracle.
- **Revisit trigger:** upstream merges the fix ⟹ re-sync the port to `−sy`. At that point C++ ==
  the exact Hessian, and finite differences become a valid oracle for the *full* Hessian.
- **Upstream:** issue/PR not yet filed (draft pending — include the derivation above).
- **Verification:** Rust `autoware_ndt_scan_matcher_rs/src/derivatives.rs` mirrors `+sy`; the FD tests
  validate the gradient + the translation Hessian rows (exact); the angle-angle Hessian block is
  validated against the C++ `NdtResult.hessian` at E4d. Related memory: `ndt-pcl-hessian-quirk`.
  (Recommended companion, not yet added: an in-code `PORT-QUIRK` marker on the `h_ang` row + a pin
  test that fails loudly if the value is changed.)
