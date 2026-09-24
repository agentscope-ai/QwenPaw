//! Versioned contract shared by the desktop runtime and native helper.

/// Request/response contract spoken by the Computer Use plugin and helper.
pub(crate) const VERSION: u64 = 2;

/// Logical method namespace selected during the hello handshake.
#[allow(dead_code)] // Used by the helper binary, not the desktop library target.
pub(crate) const COMPUTER_USE_CONTRACT: &str = "computer_use";

/// Computer Use semantics evolve independently from the wire envelope.
#[allow(dead_code)] // Used by the helper binary, not the desktop library target.
pub(crate) const COMPUTER_USE_CONTRACT_VERSION: u64 = 2;

/// Record-only contract layered over the same authenticated transport.
#[allow(dead_code)] // Used by the helper binary and the Python EventStream client.
pub(crate) const EVENT_STREAM_CONTRACT: &str = "event_stream";

/// First file-backed EventStream contract. Its staging schema is versioned
/// independently from the final Workspace recording schema.
#[allow(dead_code)]
pub(crate) const EVENT_STREAM_CONTRACT_VERSION: u64 = 1;

/// Coarse capabilities advertised without exposing platform-specific details.
#[allow(dead_code)] // Used by the helper binary, not the desktop library target.
pub(crate) const COMPUTER_USE_FEATURES: &[&str] = &["computer_use.observe", "computer_use.act"];

#[allow(dead_code)]
pub(crate) const EVENT_STREAM_FEATURE: &str = "event_stream.record";
