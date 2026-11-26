//! Shared helpers for unit tests.

use std::path::PathBuf;

/// A unique directory under the system temporary directory, removed on drop.
pub(crate) struct TestDirectory(pub(crate) PathBuf);

impl TestDirectory {
    pub(crate) fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("qwenpaw-desktop-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    pub(crate) fn child(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        // Best effort: a cleanup panic while a test is already failing would
        // abort the run and hide the original assertion.
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
