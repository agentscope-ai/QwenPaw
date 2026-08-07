//! Resolve configured agent workspaces and files across desktop commands.

use std::path::{Component, Path, PathBuf};

/// Resolve a file relative to the configured agent workspace.
pub(crate) fn resolve_agent_workspace_file_path(
    relative_path: &str,
    agent_id: &str,
) -> Result<PathBuf, String> {
    resolve_agent_artifact_file_path(relative_path, agent_id, "workspace")
}

/// Resolve a file relative to one controlled artifact root.
pub(crate) fn resolve_agent_artifact_file_path(
    relative_path: &str,
    agent_id: &str,
    root: &str,
) -> Result<PathBuf, String> {
    if relative_path.trim().is_empty() {
        return Err("file path is empty".into());
    }
    let root_dir = match root {
        "workspace" => get_agent_workspace_directory(agent_id)?,
        "project" => get_coding_directory(Some(agent_id))?,
        _ => return Err("artifact root must be project or workspace".into()),
    };
    let canonical_root = root_dir.canonicalize().map_err(|err| {
        format!(
            "failed to resolve artifact root '{}': {err}",
            root_dir.display()
        )
    })?;
    let target = root_dir.join(relative_path);
    let canonical_target = target.canonicalize().map_err(|err| {
        format!("failed to resolve file path '{}': {err}", target.display())
    })?;
    if !canonical_target.starts_with(&canonical_root) {
        return Err("path traversal detected".into());
    }
    if !canonical_target.is_file() {
        return Err("artifact path is not a file".into());
    }
    Ok(canonical_target)
}

pub(crate) fn get_agent_workspace_directory(
    agent_id: &str,
) -> Result<PathBuf, String> {
    let working_dir = get_working_directory()?;
    let config_path = working_dir.join("config.json");
    if !config_path.exists() {
        validate_fallback_agent_id(agent_id)?;
        return Ok(working_dir.join("workspaces").join(agent_id));
    }
    let content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("failed to read config.json: {err}"))?;
    let config: serde_json::Value = serde_json::from_str(&content)
        .map_err(|err| format!("failed to parse config.json: {err}"))?;
    let profile = config
        .get("agents")
        .and_then(|agents| agents.get("profiles"))
        .and_then(|profiles| profiles.get(agent_id))
        .ok_or_else(|| format!("agent '{agent_id}' not found in config"))?;
    Ok(profile
        .get("workspace_dir")
        .and_then(|path| path.as_str())
        .map(|path| resolve_configured_path(path, &working_dir))
        .unwrap_or_else(|| working_dir.join("workspaces").join(agent_id)))
}

/// Get the configured coding project or agent workspace directory.
pub(crate) fn get_coding_directory(
    agent_id: Option<&str>,
) -> Result<PathBuf, String> {
    let working_dir = get_working_directory()?;
    let config_path = working_dir.join("config.json");
    if !config_path.exists() {
        return Ok(working_dir);
    }

    let config_content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("failed to read config.json: {err}"))?;
    let config: serde_json::Value = serde_json::from_str(&config_content)
        .map_err(|err| format!("failed to parse config.json: {err}"))?;
    let target_agent = agent_id.unwrap_or_else(|| {
        config
            .get("agents")
            .and_then(|agents| agents.get("active_agent"))
            .and_then(|active| active.as_str())
            .unwrap_or("default")
    });
    let profile = config
        .get("agents")
        .and_then(|agents| agents.get("profiles"))
        .and_then(|profiles| profiles.get(target_agent))
        .ok_or_else(|| format!("agent '{target_agent}' not found in config"))?;
    let workspace_dir = profile
        .get("workspace_dir")
        .and_then(|path| path.as_str())
        .map(|path| resolve_configured_path(path, &working_dir))
        .unwrap_or_else(|| working_dir.join("workspaces").join(target_agent));

    let agent_config_path = workspace_dir.join("agent.json");
    if agent_config_path.is_file() {
        if let Ok(content) = std::fs::read_to_string(&agent_config_path) {
            if let Ok(agent_config) =
                serde_json::from_str::<serde_json::Value>(&content)
            {
                let project_dir = agent_config
                    .get("project_dir")
                    .and_then(|path| path.as_str())
                    .filter(|path| !path.trim().is_empty())
                    .or_else(|| {
                        agent_config
                            .get("coding_mode")
                            .and_then(|coding| coding.get("project_dir"))
                            .and_then(|path| path.as_str())
                            .filter(|path| !path.trim().is_empty())
                    });
                if let Some(project_dir) = project_dir
                    .map(|path| resolve_configured_path(path, &working_dir))
                {
                    return Ok(project_dir);
                }
            }
        }
    }
    Ok(workspace_dir)
}

fn expand_tilde(path: &str) -> PathBuf {
    if path == "~" || path.starts_with("~/") || path.starts_with("~\\") {
        if let Some(home) = dirs::home_dir() {
            if path == "~" {
                return home;
            }
            return home.join(&path[2..]);
        }
    }
    PathBuf::from(path)
}

pub(crate) fn resolve_configured_path(
    path: &str,
    working_dir: &Path,
) -> PathBuf {
    let expanded = expand_tilde(path);
    if expanded.is_absolute() {
        expanded
    } else {
        working_dir.join(expanded)
    }
}

fn get_working_directory() -> Result<PathBuf, String> {
    let configured = std::env::var("QWENPAW_WORKING_DIR")
        .or_else(|_| std::env::var("COPAW_WORKING_DIR"));
    if let Ok(path) = configured {
        let current = std::env::current_dir()
            .map_err(|err| format!("failed to get current directory: {err}"))?;
        return Ok(resolve_configured_path(&path, &current));
    }

    let home = dirs::home_dir().ok_or("failed to get home directory")?;
    let legacy = home.join(".copaw");
    Ok(if legacy.exists() {
        legacy
    } else {
        home.join(".qwenpaw")
    })
}

fn validate_fallback_agent_id(agent_id: &str) -> Result<(), String> {
    let path = Path::new(agent_id);
    let mut components = path.components();
    if !matches!(components.next(), Some(Component::Normal(_)))
        || components.next().is_some()
        || agent_id.chars().any(|ch| ch == '\0' || ch.is_control())
    {
        return Err("agent id is not a safe path component".into());
    }
    Ok(())
}
