use std::cmp::Ordering;

use semver::Version;
use tauri_plugin_updater::RemoteRelease;

#[derive(Debug, Clone, Copy, Eq, Ord, PartialEq, PartialOrd)]
enum PreRelease {
    NegativeInfinity,
    Alpha(u64),
    Beta(u64),
    Rc(u64),
    Infinity,
}

#[derive(Debug, Clone, Copy, Eq, Ord, PartialEq, PartialOrd)]
enum ReleaseNumber {
    NegativeInfinity,
    Number(u64),
    Infinity,
}

#[derive(Debug, Clone, Copy, Eq, Ord, PartialEq, PartialOrd)]
struct Pep440Key {
    major: u64,
    minor: u64,
    patch: u64,
    pre: PreRelease,
    post: ReleaseNumber,
    dev: ReleaseNumber,
}

/// Tauri's SemVer parser preserves build metadata but does not order it.
/// QwenPaw uses `+post.N` to carry PEP 440 post releases, so compare the
/// version forms emitted by the packaging scripts using PEP 440 precedence.
fn compare_pep440(a: &Version, b: &Version) -> Option<Ordering> {
    Some(pep440_key(a)?.cmp(&pep440_key(b)?))
}

fn pep440_key(version: &Version) -> Option<Pep440Key> {
    let (pre, dev) = parse_prerelease(version.pre.as_str())?;
    let post = parse_post_metadata(version.build.as_str())?;

    let pre = match pre {
        Some(("alpha", number)) => PreRelease::Alpha(number),
        Some(("beta", number)) => PreRelease::Beta(number),
        Some(("rc", number)) => PreRelease::Rc(number),
        Some(_) => return None,
        None if post.is_none() && dev.is_some() => PreRelease::NegativeInfinity,
        None => PreRelease::Infinity,
    };

    let post = match post {
        Some(number) => ReleaseNumber::Number(number),
        None => ReleaseNumber::NegativeInfinity,
    };
    let dev = match dev {
        Some(number) => ReleaseNumber::Number(number),
        None => ReleaseNumber::Infinity,
    };

    Some(Pep440Key {
        major: version.major,
        minor: version.minor,
        patch: version.patch,
        pre,
        post,
        dev,
    })
}

fn parse_prerelease(value: &str) -> Option<(Option<(&str, u64)>, Option<u64>)> {
    if value.is_empty() {
        return Some((None, None));
    }

    let parts: Vec<_> = value.split('.').collect();
    match parts.as_slice() {
        ["dev", dev] => Some((None, Some(dev.parse().ok()?))),
        [pre, number] => Some((Some((*pre, number.parse().ok()?)), None)),
        [pre, number, "dev", dev] => {
            Some((Some((*pre, number.parse().ok()?)), Some(dev.parse().ok()?)))
        }
        _ => None,
    }
}

fn parse_post_metadata(value: &str) -> Option<Option<u64>> {
    if value.is_empty() {
        return Some(None);
    }

    let parts: Vec<_> = value.split('.').collect();
    match parts.as_slice() {
        ["post", number] => Some(Some(number.parse().ok()?)),
        _ => None,
    }
}

pub(crate) fn is_remote_update_newer(current: Version, update: RemoteRelease) -> bool {
    match compare_pep440(&update.version, &current) {
        Some(ordering) => ordering == Ordering::Greater,
        None => {
            log::warn!(
                "[updates] unsupported updater version format current={} update={}, falling back to SemVer ordering",
                current,
                update.version,
            );
            update.version > current
        }
    }
}

pub(super) fn version_lte(a: &str, b: &str) -> bool {
    let a = a.trim_start_matches('v');
    let b = b.trim_start_matches('v');
    match (Version::parse(a), Version::parse(b)) {
        (Ok(va), Ok(vb)) => match compare_pep440(&va, &vb) {
            Some(ordering) => ordering != Ordering::Greater,
            None => {
                log::warn!(
                    "[updates] unsupported cached update version format cached={a} current={b}, falling back to SemVer ordering"
                );
                va <= vb
            }
        },
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

#[cfg(test)]
mod tests {
    use super::*;

    fn version_gt(a: &str, b: &str) -> bool {
        let a = Version::parse(a).unwrap();
        let b = Version::parse(b).unwrap();
        compare_pep440(&a, &b) == Some(Ordering::Greater)
    }

    #[test]
    fn post_release_is_newer_than_base_release() {
        assert!(version_gt("2.0.0+post.1", "2.0.0"));
    }

    #[test]
    fn post_releases_order_by_post_number() {
        assert!(version_gt("2.0.0+post.2", "2.0.0+post.1"));
    }

    #[test]
    fn patch_release_is_newer_than_a_previous_post_release() {
        assert!(version_gt("2.0.1", "2.0.0+post.99"));
    }

    #[test]
    fn prereleases_and_dev_releases_sort_before_their_release() {
        assert!(version_gt("2.0.0-alpha.1", "2.0.0-dev.1"));
        assert!(version_gt("2.0.0", "2.0.0-rc.1"));
        assert!(version_gt("2.0.0-alpha.1", "2.0.0-alpha.1.dev.1"));
    }

    #[test]
    fn cached_update_comparison_honors_post_metadata() {
        assert!(version_lte("2.0.0", "2.0.0+post.1"));
        assert!(!version_lte("2.0.0+post.1", "2.0.0"));
    }
}
