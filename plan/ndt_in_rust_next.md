# Implementation Roadmap: Rustification of Autoware NDT Scan Matcher while Keeping rclcpp as the ROS 2 Runtime Layer

## Goal

Refactor the Autoware NDT Scan Matcher so that the core NDT scan matching logic, node state, validation logic, convergence checks, covariance estimation, map update decisions, and callback body behavior are implemented in Rust.

The C++ side must remain responsible only for the ROS 2 runtime boundary:

* `rclcpp::Node` construction
* publisher/subscriber/service/timer creation
* ROS 2 parameter declaration and reading
* callback entry points
* actual ROS message publication
* TF lookup through `tf2_ros`
* map loader service calls
* diagnostics publication through existing Autoware/ROS 2 APIs
* component registration

The target design is:

```text
C++ / rclcpp shell
  - ROS 2 initialization
  - subscriptions, publishers, services, timers
  - callback entry points
  - TF lookup
  - actual message publication
  - diagnostics publication
  - map loader service call

        ↓ C ABI / FFI

Rust / NDTScanMatcherRs
  - NDT engine
  - scan matching state
  - initial pose buffer
  - regularization pose buffer
  - activation state
  - map update state
  - convergence judgment
  - covariance estimation
  - align-service logic
  - diagnostics content generation
  - publish-decision logic
```

The final C++ callback body should be approximately this thin:

```cpp
void NDTScanMatcher::callback_sensor_points(
  sensor_msgs::msg::PointCloud2::ConstSharedPtr msg)
{
  AwHost host = make_host();
  AwPointCloud2View view = make_pointcloud2_view(*msg);

  autoware_ndt_scan_matcher_rs_on_sensor_points(
    rs_.raw(), &host, &view);
}
```

Do not move the ROS 2 runtime to Rust. Do not introduce `rclrs` as the node runtime. The node should continue to run through `rclcpp`.

---

# Non-Goals

Do not implement a full Rust wrapper around ROS 2.

Do not expose `rclcpp::Node`, `rclcpp::Publisher`, `rclcpp::Subscription`, `tf2_ros::Buffer`, `std::shared_ptr`, `std::vector`, `std::string`, `Eigen`, or PCL types directly across the FFI boundary.

Do not make Rust subscribe to topics directly.

Do not make Rust own or call `rclcpp`.

Do not keep adding small Rust calls inside the existing C++ algorithmic callback body. That approach increases `#ifdef` usage and makes the code harder to maintain.

The desired direction is not:

```text
C++ callback body
  - do some logic
  - #ifdef NDT_USE_RUST call Rust
  - do more logic
  - #ifdef NDT_USE_RUST call Rust again
  - do more logic
```

The desired direction is:

```text
C++ callback body
  - create thin message view
  - create host interface
  - call one Rust on_* function
```

---

# Architectural Target

## C++ Layer

The C++ layer should become a thin ROS 2 shell.

It should own:

```cpp
class NDTScanMatcher : public rclcpp::Node
{
public:
  explicit NDTScanMatcher(const rclcpp::NodeOptions & options);

private:
  NDTScanMatcherRS rs_;

  // ROS 2 publishers
  // ROS 2 subscribers
  // ROS 2 services
  // ROS 2 timers
  // tf2 buffer/listener
  // diagnostics interface
  // map loader client

  AwHost make_host();

  void callback_sensor_points(sensor_msgs::msg::PointCloud2::ConstSharedPtr msg);
  void callback_initial_pose(
    geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg);
  void callback_regularization_pose(
    geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg);
  void callback_timer();
  void service_trigger_node(...);
  void service_ndt_align(...);
};
```

The C++ layer should not own core NDT state such as:

```text
initial pose buffer
regularization pose buffer
activation state
skipping_publish_num
map update state
NDT convergence state
latest transform probability
latest iteration count
latest covariance estimation result
map update decision state
```

Those should move to Rust.

---

## Rust Layer

The Rust side is **two layers**, not one — this split already exists in the crate and must be
preserved (it is the reason the port exists: the same core runs under a `no_std` kernel):

**(a) Portable core (`no_std`).** The algorithm lives in a `ScanMatcher` that is **generic over the
host ports** and wraps the persistent `NdtEngine`. It has no ROS, no FFI, no `std` dependency, and
reuses the pure `convergence` / `covariance` / `cov_estimate` modules. This is the awkernel /
Track-B target.

```rust
// src/scan_matcher.rs — the real type (abbreviated)
pub struct ScanMatcher {
    engine: NdtEngine,                       // src/engine.rs — &self-only, Sync, ArcSwap map
}
impl ScanMatcher {
    pub async fn update_map<S: MapSource>(&self, source: &S, center: [f64; 2], radius: f64);
    pub fn match_scan(&self, guess: &Matrix4<f32>, source: &[[f32; 3]]) -> MatchResult;          // sync, WCET
    pub fn match_scan_with_covariance(&self, ...) -> (MatchResult, CovarianceResult);            // sync
}
```

**(b) `std`-only FFI node shell.** The opaque handle C++ holds is `NdtScanMatcherRs` — the `std`
wrapper that owns the *node-level* state the algorithm core does not (pose buffers, activation,
map-update bookkeeping, diagnostics) and adapts everything to the C ABI. It lives in the
`#[cfg(feature = "std")]` `node` / `node_map_update` modules and is **never** compiled into the
`no_std` rlib.

```rust
// The std FFI shell that owns node state + drives the portable ScanMatcher.
pub struct NdtScanMatcherRs {
    matcher: ScanMatcher,                    // the portable core (owns the engine)
    state: NodeState,
    initial_pose_buffer: SmartPoseBuffer,
    regularization_pose_buffer: PoseBuffer,
    map_update_state: MapUpdateState,
}

pub struct NodeState {
    is_activated: bool,
    latest_ekf_pose: Option<TimedPose>,
    latest_sensor_points_stamp: Option<Time>,
    skipping_publish_num: i64,
    diagnostics: DiagnosticsState,
}

pub struct MapUpdateState {
    last_update_position: Option<Point3d>,
    loaded_map_ids: Vec<String>,
    need_rebuild: bool,
}
```

**no_std gating (already in place — do not regress).** `lib.rs` is `#![cfg_attr(not(any(test,
feature = "std")), no_std)]`. The `scan_matcher`, `host`, `engine`, `convergence`, `covariance`,
`cov_estimate` modules are `no_std`; `node` and `node_map_update` (the FFI node shell) are
`#[cfg(feature = "std")]`. The `std` feature pulls `arc-swap` (the lock-free engine double-buffer);
`--no-default-features` uses a single-threaded `RefCell` instead. The `ros` feature pulls `bindgen`
for the `geometry_msgs` C structs. New algorithmic code goes in the portable core so the kernel
build keeps it; only the ROS/FFI glue may be `std`-gated.

Rust should expose only C ABI functions to C++ (these wrap the `std` shell):

```rust
extern "C" fn autoware_ndt_scan_matcher_rs_new(...) -> *mut NdtScanMatcherRs;
extern "C" fn autoware_ndt_scan_matcher_rs_free(ptr: *mut NdtScanMatcherRs);

extern "C" fn autoware_ndt_scan_matcher_rs_on_sensor_points(...);
extern "C" fn autoware_ndt_scan_matcher_rs_on_initial_pose(...);
extern "C" fn autoware_ndt_scan_matcher_rs_on_regularization_pose(...);
extern "C" fn autoware_ndt_scan_matcher_rs_on_timer(...);
extern "C" fn autoware_ndt_scan_matcher_rs_on_trigger(...);
extern "C" fn autoware_ndt_scan_matcher_rs_on_ndt_align_service(...);
```

---

# FFI Design Requirements

## Use an Opaque Rust Handle

C++ must not know the layout of `NdtScanMatcherRs`.

Use a C++ RAII wrapper:

```cpp
class NDTScanMatcherRS
{
public:
  explicit NDTScanMatcherRS(const AwNdtParams & params)
  : handle_(autoware_ndt_scan_matcher_rs_new(&params))
  {
    if (!handle_) {
      throw std::runtime_error("failed to create Rust NDTScanMatcher");
    }
  }

  ~NDTScanMatcherRS()
  {
    autoware_ndt_scan_matcher_rs_free(handle_);
  }

  NDTScanMatcherRS(const NDTScanMatcherRS &) = delete;
  NDTScanMatcherRS & operator=(const NDTScanMatcherRS &) = delete;

  NDTScanMatcherRS(NDTScanMatcherRS &&) = delete;
  NDTScanMatcherRS & operator=(NDTScanMatcherRS &&) = delete;

  AwNdtScanMatcher * raw() { return handle_; }

private:
  AwNdtScanMatcher * handle_{nullptr};
};
```

Rust should return a boxed pointer:

```rust
#[unsafe(no_mangle)]
pub unsafe extern "C" fn autoware_ndt_scan_matcher_rs_new(
    params: *const AwNdtParams,
) -> *mut NdtScanMatcherRs {
    ffi_boundary_ptr(|| {
        let params = unsafe { params.as_ref() }.ok_or(Error::NullPtr)?;
        let params = Params::try_from_ffi(params)?;
        Ok(Box::into_raw(Box::new(NdtScanMatcherRs::new(params)?)))
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn autoware_ndt_scan_matcher_rs_free(
    ptr: *mut NdtScanMatcherRs,
) {
    if !ptr.is_null() {
        unsafe {
            drop(Box::from_raw(ptr));
        }
    }
}
```

---

## Use Plain C ABI Types Only

Allowed across FFI:

```text
raw pointer + length
fixed-size numeric arrays
i32/u32/i64/u64/f32/f64
bool represented explicitly
opaque handles
repr(C) structs
repr(C) enums with explicit integer representation
```

Do not expose these across FFI:

```text
std::string
std::vector
std::shared_ptr
Eigen::Matrix
pcl::PointCloud
rclcpp types
tf2 types
Rust Vec
Rust String
Rust references with non-FFI-safe layout
```

---

## Introduce FFI View Types

Use thin borrowed views for ROS messages.

Example string view:

```rust
#[repr(C)]
pub struct AwStr {
    pub ptr: *const u8,
    pub len: usize,
}
```

Example pose:

```rust
#[repr(C)]
pub struct AwPose {
    pub position_xyz: [f64; 3],
    pub orientation_xyzw: [f64; 4],
}
```

Example stamped pose with covariance:

```rust
#[repr(C)]
pub struct AwPoseWithCovarianceStampedView {
    pub stamp_ns: i64,
    pub frame_id: AwStr,
    pub pose: AwPose,
    pub covariance_6x6_row_major: [f64; 36],
}
```

Example point cloud view:

```rust
#[repr(C)]
pub struct AwPointCloud2View {
    pub stamp_ns: i64,
    pub frame_id: AwStr,

    pub height: u32,
    pub width: u32,
    pub point_step: u32,
    pub row_step: u32,

    pub data: *const u8,
    pub data_len: usize,

    pub x_offset: i32,
    pub y_offset: i32,
    pub z_offset: i32,

    pub is_bigendian: bool,
}
```

Rust may read these views only during the FFI call. Rust must never store raw pointers into C++ message memory.

If Rust needs to retain data, copy it into Rust-owned structures.

---

## The Host Abstraction: a Rust Trait, with the C Vtable as One Adapter

**The host abstraction is a portable Rust trait, not the C vtable.** This already exists in
`src/host.rs`:

```rust
pub trait MapSource { fn load(&self, center: [f64; 2], radius: f64) -> impl Future<Output = MapDelta>; }
pub trait OutputSink { fn publish_result(&self, result: &MatchResult); }
pub trait Clock      { fn now_ns(&self) -> i64; }
pub trait Host: MapSource + OutputSink + Clock {}     // blanket-impl'd
```

Portable node logic takes `host: &H` with `H: Host` and never names ROS. The runtime is chosen by
which adapter implements the trait:

- **ROS adapter** — a Rust `FfiHost` that implements `Host` on top of the C-ABI vtable below (the
  `ctx` is the `NDTScanMatcher *`). The `AwHost` struct is **this adapter's transport**, not the
  abstraction itself.
- **Tokio adapter** — `examples/tokio_ndt.rs`, the async reference impl over synthetic data.
- **Kernel adapter** (future) — its own async runtime + map source (flash/DMA).

**Async I/O, synchronous align.** Map loading is inherently I/O (a ROS service future, a kernel DMA
read), so the `MapSource::load` port is **`async`** (return-position `impl Future`, no boxing/`Send`
bound — clean in `no_std`). The engine **align hot path stays synchronous** for WCET; it runs
between awaits, never `async`. A coding agent must therefore **not** model map delta as a blocking
`request_map_delta(... out_delta) -> AwStatus`: a synchronous map-loader service call inside a ROS
callback can deadlock under a single-threaded executor. The ROS adapter bridges the async port to
the rclcpp service client; see `apply_map_update` in `src/scan_matcher.rs` for the realized
staging-build-then-`commit_from` flow.

### The ROS adapter surface (C-ABI vtable)

Below the `FfiHost` adapter, ROS side effects cross as a `#[repr(C)]` vtable of C function pointers
over an opaque `ctx`. Rust must not publish directly; it requests side effects through this vtable.

```rust
#[repr(C)]
pub struct AwHost {
    pub ctx: *mut core::ffi::c_void,

    pub now_ns: extern "C" fn(ctx: *mut core::ffi::c_void) -> i64,

    pub lookup_transform: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        target_frame: AwStr,
        source_frame: AwStr,
        stamp_ns: i64,
        out_matrix4x4_row_major: *mut f32,
    ) -> AwStatus,

    pub publish_pose: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        topic: AwPoseTopic,
        stamp_ns: i64,
        frame_id: AwStr,
        pose: *const AwPose,
        covariance_6x6_row_major: *const f64,
    ) -> AwStatus,

    pub publish_pointcloud_xyz: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        topic: AwPointCloudTopic,
        stamp_ns: i64,
        frame_id: AwStr,
        points_xyz: AwPoint3fSlice,
    ) -> AwStatus,

    pub publish_diagnostic: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        record: *const AwDiagnosticRecord,
    ) -> AwStatus,

    pub request_map_delta: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        center_x: f64,
        center_y: f64,
        radius: f64,
        cached_map_ids: AwStrList,
        out_delta: *mut AwMapDeltaBuilder,
    ) -> AwStatus,

    pub log: extern "C" fn(
        ctx: *mut core::ffi::c_void,
        level: AwLogLevel,
        message: AwStr,
    ),
}
```

C++ implements each callback by casting `ctx` back to `NDTScanMatcher *`.

```cpp
extern "C" AwStatus aw_publish_pose(
  void * ctx,
  AwPoseTopic topic,
  int64_t stamp_ns,
  AwStr frame_id,
  const AwPose * pose,
  const double * covariance)
{
  auto * self = static_cast<NDTScanMatcher *>(ctx);

  try {
    auto msg = make_pose_message(stamp_ns, to_string(frame_id), *pose, covariance);
    self->publish_pose(topic, msg);
    return AW_OK;
  } catch (...) {
    return AW_ERR_PUBLISH_FAILED;
  }
}
```

Keep the Host interface small. Host is only for ROS side effects, not for algorithm state.

Good Host responsibilities:

```text
now()
lookup_transform()
publish_pose()
publish_pointcloud()
publish_diagnostic()
request_map_delta()
log()
```

Bad Host responsibilities:

```text
push_initial_pose()
set_is_activated()
get_regularization_pose_buffer()
set_skipping_publish_num()
run_convergence_check()
estimate_covariance()
```

Those should be Rust-owned logic.

**Transitional debt to remove.** The current `NdtHost` vtable in `src/node.rs` *does* expose exactly
these "bad" setters — `set_activated`, `clear_initial_pose_buffer`, `push_initial_pose`,
`push_regularization_pose`, `set_latest_ekf_position` — because node state still lives C++-side. That
is a deliberate stepping stone, **not** the target. As Phases 1–4 move that state into
`NdtScanMatcherRs`, these setters are deleted and the vtable shrinks to ROS side effects only.

---

# Error Handling Requirements

All Rust FFI entry points must catch errors and convert them to `AwStatus`.

No Rust panic may unwind into C++.

Use a common FFI boundary helper:

```rust
fn ffi_boundary<F>(f: F) -> AwStatus
where
    F: FnOnce() -> Result<(), Error> + std::panic::UnwindSafe,
{
    match std::panic::catch_unwind(f) {
        Ok(Ok(())) => AwStatus::Ok,
        Ok(Err(e)) => e.into_status(),
        Err(_) => AwStatus::Panic,
    }
}
```

For functions returning pointers:

```rust
fn ffi_boundary_ptr<T, F>(f: F) -> *mut T
where
    F: FnOnce() -> Result<*mut T, Error> + std::panic::UnwindSafe,
{
    match std::panic::catch_unwind(f) {
        Ok(Ok(ptr)) => ptr,
        _ => std::ptr::null_mut(),
    }
}
```

C++ should log non-OK statuses returned by Rust.

---

# Threading Requirements

Assume the node may run under a `MultiThreadedExecutor`, so Rust state must be safe under concurrent
callback entry. **Do not reach for a giant `Mutex<NdtScanMatcherInner>`** — the engine already
solved this lock-free, and a wrapping mutex would serialize callbacks and undo it.

**Engine (done — `src/engine.rs`).** `NdtEngine` exposes **`&self`-only** methods and is `Sync`. The
target map + params live in an `ArcSwap<EngineState>`: the align/read path `load`s an immutable
snapshot **lock-free** (no lock held across alignment — the "snapshot then align" intent, realized
without a lock). Map updates do not mutate in place: `apply_map_update` builds the new map on a
**private staging engine**, then `commit_from` atomically swaps it in (a lock-free double-buffer), so
a concurrent align never observes a partial map. Regularization is a second `ArcSwap`; the per-align
scratch (workspace + last result) is a **thread-local** under `std` and a `RefCell` under `no_std`
(single-threaded). End goal (memory `ndt-engine-ffi-locking`): a `const` handle, `&self`-only,
ArcSwap map — **no giant lock**.

**Node shell (to build).** The `std` `NdtScanMatcherRs` still owns genuinely-mutable node state the
engine does not — pose buffers, activation flag, `skipping_publish_num`, map-update bookkeeping.
That state needs its *own* lightweight synchronization (e.g. a small mutex per buffer, or atomics for
flags/counters), kept **separate from and finer-grained than** the lock-free engine. The principle
stands: never hold a node-state lock across an alignment, and never call a C++ Host function while
holding one.

---

# Current State vs Target

This roadmap is **consolidation, not greenfield**. The crate already has most of the hard parts; the
phases below mostly *move ownership* and *thin the boundary*, not build from scratch. Where things
stand today:

| Already built | Where | Subsumed by |
|---|---|---|
| Portable `Host` trait (`MapSource`/`OutputSink`/`Clock`) + generic `ScanMatcher` core | `src/host.rs`, `src/scan_matcher.rs` | the architecture target (don't rebuild) |
| Lock-free engine (`&self`-only, `ArcSwap` map, `commit_from`, async `apply_map_update`) | `src/engine.rs` | Threading Requirements (done) |
| Pure convergence + covariance kernels | `src/convergence.rs`, `src/covariance.rs`, `src/cov_estimate.rs` | reused by Phases 5/7 |
| Tokio reference adapter | `examples/tokio_ndt.rs` | proves the `Host` seam |
| Fine-grained, **function-level** FFI (e.g. `..._ndt_engine_align`, `..._node_on_initial_pose`, `..._node_estimate_pose_covariance`) | `src/engine.rs`, `src/node.rs` | collapses into the `on_*` callback forwarders (Phases 2–7) |
| Transitional `NdtHost` vtable with **node-state setters** (`set_activated`, `push_initial_pose`, …) | `src/node.rs` | deleted as state moves to Rust (Phases 1–4) |
| **Opaque node handle `NdtScanMatcherRs` + `_new`/`_free`** + `AwNdtParams` param conversion (foundation slice, 2026-06-30) | `src/node_handle.rs`, C++ `ndt_scan_matcher_rs.hpp` (`NDTScanMatcherRS` RAII + `make_aw_ndt_params`), node member `rs_` | **inert today** — fills with state over Phases 1–6 |
| **Panic-safe FFI boundary** (`catch_unwind` → `AwStatus`/null) (foundation slice, 2026-06-30) | `src/ffi.rs` (`ffi_boundary`/`ffi_boundary_ptr`) | the Error-Handling requirement; later `on_*` entry points adopt it |
| **Regularization pose buffer → Rust** + `SmartPoseBuffer` port (`PoseBuffer`) + `AwPoseWithCovarianceStampedView` (Phase 1 slice A, 2026-06-30) | `src/pose_buffer.rs`, handle `Mutex<PoseBuffer>`, `..._regularization_interpolate` FFI | **done** — `on_regularization_pose` drives the Rust buffer; 1 of 6 host setters removed |

So the net of the phases is: (1) give the `std` `NdtScanMatcherRs` shell ownership of the node state
C++ still holds, (2) replace the many function-level FFI calls with one `on_*` forwarder per
callback, and (3) shrink the host vtable to ROS side effects only. **The opaque handle + panic
boundary (commit-sequence items 2 & 4) landed 2026-06-30** — Phase 0 is substantially complete; the
handle is held as the node's `rs_` member but does not yet own state or drive any callback.

# Phased Implementation Plan

## Phase 0: Stabilize the Rust FFI Surface

### Objective

Create a clean, explicit FFI boundary that can support the final architecture.

### Tasks

1. Define or clean up the C ABI types:

```text
AwStatus
AwStr
AwTime
AwPose
AwPoseWithCovarianceStampedView
AwPointCloud2View
AwPoint3fSlice
AwNdtParams
AwHost
AwDiagnosticRecord
AwMapDeltaBuilder
```

2. Ensure all exported Rust functions use only C ABI-safe types.

3. Generate the C/C++ header through `cbindgen`. (FFI mechanism is **settled**: a hand-rolled C ABI
   with a cbindgen-generated header — the single source of truth. The `cxx` approach sketched in the
   older `plan/callback_level_rust.md` is **superseded**; do not reintroduce it.)

4. Add C++ compile checks to ensure the generated header is usable from the existing package.

5. Add a C++ RAII wrapper `NDTScanMatcherRS`.

### Acceptance Criteria

* ✅ C++ can construct and destroy `NDTScanMatcherRS` (RAII wrapper over `_new`/`_free`; gtest
  `test_ndt_scan_matcher_rs_handle`).
* ✅ No C++ code depends on the internal layout of Rust structs (`AwNdtScanMatcher` is opaque).
* ✅ `AwNdtParams` crosses as a C-ABI-safe struct (scalars + `(ptr, len)` offset models, copied
  Rust-side).
* ✅ Rust panics cannot unwind into C++ (`ffi.rs` `catch_unwind` → `AwStatus::Panic`/null).
* ◻ Remaining: the full view-type set (`AwPose`/`AwPointCloud2View`/…) + the consolidated `AwHost`
  land with the callbacks that need them (Phases 2–7); the ~50 existing function-level FFIs adopt
  the `ffi_boundary` helper as they fold into `on_*` forwarders.

---

## Phase 1: Make Rust Own the Main NDTScanMatcher State

### Objective

Move node-level algorithmic state from C++ into `NdtScanMatcherRs`.

### Move to Rust

```text
activation state
initial pose buffer
regularization pose buffer
latest EKF pose
latest sensor points metadata
skipping_publish_num
diagnostics state
map update state
```

### Keep in C++

```text
rclcpp::Node
publishers
subscribers
services
timers
tf2 buffer/listener
diagnostics publisher
map loader client
parameters declaration
```

### Tasks

1. Add the `std` shell struct. **Do not wrap everything in one `Mutex`** (see Threading
   Requirements): the `ScanMatcher`/`NdtEngine` is already `&self`-only + lock-free, so only the
   genuinely-mutable node state needs synchronization, and at a finer grain.

```rust
pub struct NdtScanMatcherRs {
    matcher: ScanMatcher,        // portable core; &self-only, lock-free engine — NOT behind a node mutex
    params: Params,
    // node-level mutable state, each with its own lightweight sync (mutex/atomics), not one giant lock:
    state: Mutex<NodeState>,
    initial_pose_buffer: Mutex<SmartPoseBuffer>,
    regularization_pose_buffer: Mutex<PoseBuffer>,
    map_update_state: Mutex<MapUpdateState>,
}
```

2. Convert C++ parameters into `AwNdtParams`.

3. Convert `AwNdtParams` into Rust `Params`.

4. Initialize all algorithmic state in Rust.

5. Remove duplicated ownership of the same state from C++ where possible.

### Acceptance Criteria

* Rust owns the scan matcher’s algorithmic state.
* C++ no longer directly mutates activation, pose buffers, or skipping counters.
* Behavior remains equivalent to the existing implementation.

---

## Phase 2: Move Initial Pose Callback Logic to Rust

### Objective

Make the C++ initial pose callback a thin forwarding function.

### Target C++ Shape

```cpp
void NDTScanMatcher::callback_initial_pose(
  geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg)
{
  AwHost host = make_host();
  AwPoseWithCovarianceStampedView view = make_pose_with_cov_view(*msg);

  const auto status =
    autoware_ndt_scan_matcher_rs_on_initial_pose(rs_.raw(), &host, &view);

  log_if_error(status);
}
```

### Rust Responsibilities

Rust should handle:

```text
frame_id validation
timestamp validation
pose conversion
initial pose buffer update
latest EKF pose update
activation-related state update
diagnostic record generation
```

### Tasks

1. Implement `autoware_ndt_scan_matcher_rs_on_initial_pose`.

2. Implement `NdtScanMatcherRs::on_initial_pose`.

3. Move initial pose buffering logic from C++ to Rust.

4. Use Host only for logging and diagnostics publication.

5. Delete or disable equivalent C++ logic after behavior is verified.

### Acceptance Criteria

* C++ initial pose callback only creates views and calls Rust.
* Rust owns the initial pose buffer.
* Rust owns the latest EKF pose state.
* Existing tests still pass.
* No new `#ifdef` blocks are added inside the callback body.

---

## Phase 3: Move Regularization Pose Callback Logic to Rust

### Objective

Make the C++ regularization pose callback a thin forwarding function.

### Target C++ Shape

```cpp
void NDTScanMatcher::callback_regularization_pose(
  geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg)
{
  AwHost host = make_host();
  AwPoseWithCovarianceStampedView view = make_pose_with_cov_view(*msg);

  const auto status =
    autoware_ndt_scan_matcher_rs_on_regularization_pose(rs_.raw(), &host, &view);

  log_if_error(status);
}
```

### Rust Responsibilities

Rust should handle:

```text
regularization pose validation
regularization pose buffer update
regularization enable/disable behavior
timestamp handling
diagnostic content generation
```

### Acceptance Criteria

* ✅ C++ callback only forwards to Rust (`on_regularization_pose(handle, diag, view)`).
* ✅ Rust owns the regularization pose buffer (`Mutex<PoseBuffer>` on the handle; the C++
  `regularization_pose_buffer_` is now `#ifndef NDT_USE_RUST` only).
* ✅ Regularization behavior matches the existing C++ implementation (differential test
  `test_regularization_buffer`, 50 random sequences). **Landed 2026-06-30 (Phase 1 slice A).**

---

## Phase 4: Move Trigger / Activation Service Logic to Rust

### Objective

Move node activation/deactivation state into Rust completely.

### Target C++ Shape

```cpp
void NDTScanMatcher::service_trigger_node(
  const std_srvs::srv::SetBool::Request::SharedPtr req,
  const std_srvs::srv::SetBool::Response::SharedPtr res)
{
  AwHost host = make_host();
  AwTriggerResponse out{};

  const auto status =
    autoware_ndt_scan_matcher_rs_on_trigger(
      rs_.raw(), &host, req->data, now().nanoseconds(), &out);

  fill_trigger_response(*res, out);
  log_if_error(status);
}
```

### Rust Responsibilities

```text
set activation state
clear or preserve internal buffers according to existing behavior
generate response success flag
generate response message
publish diagnostics if required
```

### Acceptance Criteria

* C++ does not own `is_activated`.
* C++ trigger service only forwards request and fills response.
* Behavior matches the existing trigger service.

---

## Phase 5: Move Sensor Point Callback Main Logic to Rust

### Objective

This is the most important phase. Move the body of `callback_sensor_points_main` into Rust.

The C++ sensor point callback should become a simple forwarding function.

### Target C++ Shape

```cpp
void NDTScanMatcher::callback_sensor_points(
  sensor_msgs::msg::PointCloud2::ConstSharedPtr msg)
{
  AwHost host = make_host();
  AwPointCloud2View view = make_pointcloud2_view(*msg);

  const auto status =
    autoware_ndt_scan_matcher_rs_on_sensor_points(rs_.raw(), &host, &view);

  log_if_error(status);
}
```

### Rust Responsibilities

Rust should handle:

```text
sensor point size validation
sensor point delay validation
PointCloud2 xyz decoding
TF request through Host
point cloud transform into base frame
distance validation
activation check
initial pose interpolation
old pose buffer cleanup
regularization pose selection
map range validation
map availability validation
NDT alignment execution
convergence check
covariance estimation
transform probability handling
nearest voxel transformation likelihood handling
iteration count handling
skipping_publish_num update
publish decision logic
diagnostic content generation
```

### Host Responsibilities During This Phase

C++ Host should provide:

```text
now_ns()
lookup_transform()
publish_pose()
publish_pointcloud_xyz()
publish_diagnostic()
log()
```

### Implementation Strategy

Start with a simpler but safe implementation:

1. In C++, convert `sensor_msgs::msg::PointCloud2` into a flat `xyzxyzxyz` float array.
2. Pass that flat array to Rust as `AwPoint3fSlice`.
3. Make Rust own the callback algorithm.

After behavior is stable, optimize:

1. Pass `AwPointCloud2View` directly.
2. Decode x/y/z fields in Rust — but **validate field datatype + count before decoding** (the view
   carries only byte offsets; the data is untrusted until validated, per `rust-c-ffi-safety`).
   Reject / status-error a cloud whose x/y/z are not the expected `FLOAT32` layout instead of
   reinterpreting bytes.
3. Reuse Rust-owned workspaces to reduce allocations.

### Acceptance Criteria

* C++ no longer contains the algorithmic body of `callback_sensor_points_main`.
* Sensor point callback contains no internal `NDT_USE_RUST` branches.
* Rust produces the same output poses, diagnostics, and status decisions as the previous
  implementation, verified against the **C++ engine differential-test oracle** (the
  `trace-state-machine-port-verification` workflow; findings logged in
  `porting_notes/ndt_in_rust.md`). Tolerance: pose translation ≤ 1e-3 m, rotation ≤ 1e-3 rad,
  transform-probability / NVTL ≤ 1e-4, iteration count exact; mirror any documented upstream
  divergence (e.g. the pcl Hessian quirk) rather than "fixing" it.
* Existing integration tests pass.
* New regression tests compare Rust output against the legacy C++ implementation where possible.

---

## Phase 6: Move Map Update Decision State to Rust

### Objective

Move map update policy and state into Rust while keeping the actual map loader service call in C++.

### Target C++ Timer Shape

```cpp
void NDTScanMatcher::callback_timer()
{
  AwHost host = make_host();

  const auto status =
    autoware_ndt_scan_matcher_rs_on_timer(
      rs_.raw(), &host, now().nanoseconds());

  log_if_error(status);
}
```

### Rust Responsibilities

```text
check activation state
check latest EKF/reference position availability
decide whether map update is required
track last update position
track loaded map IDs
request map delta through Host
apply map delta to NDT engine
decide whether rebuild is required
generate diagnostics
```

### C++ Responsibilities

```text
perform actual map_loader service call
convert service response into FFI map delta format
return status to Rust
```

### Acceptance Criteria

* C++ `MapUpdateModule` is either removed or reduced to a thin map-loader Host implementation.
* Rust owns `MapUpdateState`.
* Rust decides when map updates are required.
* C++ only performs ROS 2 service I/O.

---

## Phase 7: Move NDT Align Service Logic to Rust

### Objective

Move `service_ndt_align_main` and `align_pose` behavior into Rust.

### Target C++ Shape

```cpp
void NDTScanMatcher::service_ndt_align(
  const Request::SharedPtr req,
  Response::SharedPtr res)
{
  AwHost host = make_host();
  AwPoseWithCovarianceStampedView initial_pose =
    make_pose_with_cov_view(req->pose_with_covariance);

  AwNdtAlignResponse out{};

  const auto status =
    autoware_ndt_scan_matcher_rs_on_ndt_align_service(
      rs_.raw(), &host, &initial_pose, &out);

  fill_ndt_align_response(*res, out);
  log_if_error(status);
}
```

### Rust Responsibilities

```text
validate request
check activation/map/sensor point availability
perform initial pose handling
run NDT alignment
run TPE or particle-based logic if applicable
compute scores
compute covariance
decide response status
prepare response fields
prepare marker/debug outputs through Host
generate diagnostics
```

### C++ Responsibilities

```text
convert ROS request to FFI view
convert FFI response to ROS response
publish markers if Rust requests it through Host
log errors
```

### Acceptance Criteria

* C++ service body only adapts request/response and calls Rust.
* Rust owns align-service algorithmic behavior.
* Service responses match the previous implementation.
* Existing service tests pass.

---

## Phase 8: Remove Migration-Only Adapters and `#ifdef` Branches

### Objective

Remove transitional C++/Rust adapter code and eliminate function-body-level conditional compilation.

### Remove or Reduce

```text
NdtRustAdapter
NdtBackend compatibility layer
NDT_USE_RUST branches inside function bodies
C++ NDT compute fallback path from production code
algorithmic duplication between C++ and Rust
```

### Preferred Final State

Production code should not contain scattered code like:

```cpp
#ifdef NDT_USE_RUST
  ...
#else
  ...
#endif
```

If a legacy C++ implementation must remain temporarily, isolate it at the build-target level:

```cmake
if(NDT_USE_RUST)
  target_sources(${PROJECT_NAME} PRIVATE
    src/ndt_scan_matcher_rust_shell.cpp
  )
else()
  target_sources(${PROJECT_NAME} PRIVATE
    src/ndt_scan_matcher_legacy_cpp.cpp
  )
endif()
```

Do not keep conditional compilation inside large callback bodies.

### Acceptance Criteria

* `#ifdef NDT_USE_RUST` is not scattered through algorithmic functions.
* C++ production node shell is thin.
* Rust is the primary implementation of NDT Scan Matcher behavior.
* Legacy C++ code is removed, isolated, or clearly marked as temporary.

---

# Final Desired C++ Shape

The final C++ implementation should look like this conceptually:

```cpp
class NDTScanMatcher : public rclcpp::Node
{
public:
  explicit NDTScanMatcher(const rclcpp::NodeOptions & options)
  : Node("ndt_scan_matcher", options),
    rs_(make_aw_ndt_params(*this))
  {
    setup_publishers();
    setup_subscriptions();
    setup_services();
    setup_timers();
  }

private:
  NDTScanMatcherRS rs_;

  void callback_sensor_points(
    sensor_msgs::msg::PointCloud2::ConstSharedPtr msg)
  {
    AwHost host = make_host();
    AwPointCloud2View view = make_pointcloud2_view(*msg);

    const auto status =
      autoware_ndt_scan_matcher_rs_on_sensor_points(
        rs_.raw(), &host, &view);

    log_if_error(status);
  }

  void callback_initial_pose(
    geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg)
  {
    AwHost host = make_host();
    AwPoseWithCovarianceStampedView view = make_pose_with_cov_view(*msg);

    const auto status =
      autoware_ndt_scan_matcher_rs_on_initial_pose(
        rs_.raw(), &host, &view);

    log_if_error(status);
  }

  void callback_regularization_pose(
    geometry_msgs::msg::PoseWithCovarianceStamped::ConstSharedPtr msg)
  {
    AwHost host = make_host();
    AwPoseWithCovarianceStampedView view = make_pose_with_cov_view(*msg);

    const auto status =
      autoware_ndt_scan_matcher_rs_on_regularization_pose(
        rs_.raw(), &host, &view);

    log_if_error(status);
  }

  void callback_timer()
  {
    AwHost host = make_host();

    const auto status =
      autoware_ndt_scan_matcher_rs_on_timer(
        rs_.raw(), &host, now().nanoseconds());

    log_if_error(status);
  }

  void service_trigger_node(
    const std_srvs::srv::SetBool::Request::SharedPtr req,
    const std_srvs::srv::SetBool::Response::SharedPtr res)
  {
    AwHost host = make_host();
    AwTriggerResponse out{};

    const auto status =
      autoware_ndt_scan_matcher_rs_on_trigger(
        rs_.raw(), &host, req->data, now().nanoseconds(), &out);

    fill_trigger_response(*res, out);
    log_if_error(status);
  }

  void service_ndt_align(
    const tier4_localization_msgs::srv::PoseWithCovarianceStamped::Request::SharedPtr req,
    const tier4_localization_msgs::srv::PoseWithCovarianceStamped::Response::SharedPtr res)
  {
    AwHost host = make_host();
    AwPoseWithCovarianceStampedView initial_pose =
      make_pose_with_cov_view(req->pose_with_covariance);

    AwNdtAlignResponse out{};

    const auto status =
      autoware_ndt_scan_matcher_rs_on_ndt_align_service(
        rs_.raw(), &host, &initial_pose, &out);

    fill_ndt_align_response(*res, out);
    log_if_error(status);
  }
};
```

---

# Testing Strategy

## Unit Tests in Rust

Add Rust tests for:

```text
pose buffer insertion
pose buffer interpolation
regularization pose selection
activation/deactivation behavior
sensor point validation
PointCloud2 xyz decoding
transform application
convergence judgment
covariance estimation
map update decision
diagnostic record generation
```

## FFI Tests

Add tests for:

```text
construct/free lifecycle
null pointer handling
invalid parameter handling
invalid message view handling
panic containment
status conversion
string view conversion
point cloud view conversion
```

## C++ Tests

Add tests for:

```text
NDTScanMatcherRS RAII wrapper
AwHost callbacks
ROS message to FFI view conversion
FFI response to ROS response conversion
publisher dispatch by topic enum
diagnostic dispatch by diagnostic enum
map loader response conversion
```

## Regression Tests

The regression mechanism is the **C++ engine differential-test oracle** — drive the same inputs
through the legacy C++ path and the Rust path and diff the observables, per the
`trace-state-machine-port-verification` skill. Record any divergence in `porting_notes/ndt_in_rust.md`
and reproduce (do not locally fix) confirmed upstream bugs.

For each migrated phase, compare behavior against the existing C++ implementation before deleting it.

Compare:

```text
published pose
published covariance
transform probability
nearest voxel transformation likelihood
iteration count
convergence status
diagnostics
service response
map update behavior
```

Use numerical tolerances for floating-point differences.

---

# Migration Rules for the Coding Agent

Follow these rules strictly:

1. Keep `rclcpp` as the node runtime.
2. Do not introduce `rclrs` for this migration.
3. Do not build a full ROS 2 wrapper in Rust.
4. C++ callbacks should become one-call forwarders to Rust.
5. Rust should own algorithmic state.
6. C++ should own ROS 2 side effects.
7. Use Host vtable callbacks for ROS side effects.
8. Use C ABI-safe types only.
9. Do not expose C++ STL, Eigen, PCL, rclcpp, or tf2 types through FFI.
10. Do not store borrowed C++ message memory in Rust.
11. Convert borrowed FFI views into Rust-owned data before storing.
12. Do not let Rust panic unwind into C++.
13. Avoid adding new function-body-level `#ifdef` branches.
14. Prefer source-level or target-level build switching during migration.
15. After each phase, remove duplicated C++ logic if the Rust path is verified.
16. Keep behavior compatible with the existing Autoware NDT Scan Matcher.
17. Add tests before or during each migration phase.
18. Keep each commit focused on one boundary or one callback migration.

---

# Recommended Commit Sequence

Use small, reviewable commits.

```text
1. Add stable FFI types and generated C++ header.
2. Add C++ RAII wrapper for Rust NDTScanMatcherRs handle.
3. Add AwHost interface and C++ Host implementation skeleton.
4. Move parameter conversion into AwNdtParams.
5. Move initial pose buffer/state into Rust.
6. Move initial pose callback body into Rust.
7. Move regularization pose callback body into Rust.
8. Move trigger/activation service logic into Rust.
9. Move sensor point validation and PointCloud2 decoding into Rust.
10. Move sensor point callback main body into Rust.
11. Move convergence and covariance publication decisions into Rust.
12. Move map update state and decision logic into Rust.
13. Move NDT align service algorithm into Rust.
14. Remove transitional adapters.
15. Remove scattered NDT_USE_RUST branches.
16. Delete or isolate legacy C++ algorithmic implementation.
17. Add final regression tests and documentation.
```

---

# Definition of Done

The migration is complete when:

```text
C++ still runs the ROS 2 node through rclcpp.
C++ owns only ROS 2 I/O and callback entry points.
Rust owns NDT Scan Matcher state and algorithmic behavior.
C++ callbacks call exactly one Rust on_* function, plus local view/host setup.
The Rust API is exposed through opaque handles and C ABI-safe types.
No ROS 2 C++ types cross into Rust.
No Rust-owned types cross directly into C++ except opaque handles.
No Rust panic can unwind into C++.
Scattered #ifdef NDT_USE_RUST branches are removed from algorithmic code.
Behavior matches the previous C++ implementation within accepted tolerances.
Existing Autoware tests pass.
New Rust, FFI, and integration regression tests are added.
The portable core (scan matcher + engine + Host trait) still builds no_std (`--no-default-features`); only ROS/FFI glue is std-gated.
```

---

# One-Sentence Direction for the Coding Agent

Refactor the NDT Scan Matcher into a thin `rclcpp` C++ shell plus a Rust-owned `NdtScanMatcherRs` core, using C ABI-safe message views and a C++-implemented Host vtable for ROS side effects, until each C++ callback only forwards the event to one Rust `on_*` function.

