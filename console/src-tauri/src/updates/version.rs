use semver::Version;

pub(super) fn version_lte(a: &str, b: &str) -> bool {
    let a = a.trim_start_matches('v');
    let b = b.trim_start_matches('v');
    match (Version::parse(a), Version::parse(b)) {
        (Ok(va), Ok(vb)) => va <= vb,
        // If either version is unparseable we cannot prove the cached update is
        // newer than the running app, so treat it as stale (true) and let the
        // caller drop the cache rather than advertising an unverifiable update.
        (Err(err), _) => {
            log::warn!(
                "[updates] cannot parse cached update version {a}, treating as stale: {err}"
            );
            true
        }
        (_, Err(err)) => {
            log::warn!(
                "[updates] cannot parse current app version {b}, treating cache as stale: {err}"
            );
            true
        }
    }
}
