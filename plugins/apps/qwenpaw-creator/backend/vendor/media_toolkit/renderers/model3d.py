# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-locals,too-many-statements
# Vendored from Qwen-MM-Plugins (Apache-2.0), github/main commit f9d5741.
# Upstream path: src/capabilities/core/qwen_media_toolkit_core/renderers/model3d.py
#   (_load_scene, _sample_face_colors, _render_matplotlib, VIEWS).
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render 3D model files (OBJ, STL, GLB, GLTF, PLY) via trimesh + matplotlib.

Creator modifications: the upstream Blender Cycles and pyrender EGL
backends are removed — Blender stays out of Creator by design and EGL is
unavailable on the shipped platforms, so the matplotlib fallback is the
backend. Emits meta + PIL image blocks (one page per canonical view)
instead of upstream base64 blocks; STEP/STP stay unregistered (they need
a CAD kernel trimesh does not bundle).
"""

from __future__ import annotations

import io
import os
from typing import Any

_TRIMESH_HINT = (
    "Missing dependency trimesh — install with: pip install trimesh"
)

VIEWS = [
    ("Perspective", 30, 45),
    ("Front", 0, 0),
    ("Top", 90, 0),
]

MAX_MPL_FACES = 80_000


def _load_scene(path: str):
    """Load a 3D file and return (meshes, total_verts, total_faces)."""
    import trimesh

    scene = trimesh.load(path)
    meshes = (
        list(scene.geometry.values())
        if isinstance(scene, trimesh.Scene)
        else [scene]
    )
    meshes = [
        m
        for m in meshes
        if isinstance(m, trimesh.Trimesh) and len(m.faces) > 0
    ]

    if not meshes:
        raise ValueError("No renderable mesh found in file")

    total_verts = sum(len(m.vertices) for m in meshes)
    total_faces = sum(len(m.faces) for m in meshes)
    return meshes, total_verts, total_faces


def _sample_face_colors(mesh, np):
    """Sample texture color at each face's UV centroid. Nx4 RGBA or None."""
    vis = getattr(mesh, "visual", None)
    if vis is None:
        return None

    if type(vis).__name__ == "TextureVisuals":
        uv = getattr(vis, "uv", None)
        mat = getattr(vis, "material", None)
        if uv is None or mat is None:
            return None
        tex_img = getattr(mat, "baseColorTexture", None) or getattr(
            mat,
            "image",
            None,
        )
        if tex_img is None:
            return None
        tex = np.array(tex_img)
        h, w = tex.shape[:2]
        colors = np.zeros((len(mesh.faces), 4), dtype=np.float64)
        for i, face in enumerate(mesh.faces):
            centroid_uv = uv[face].mean(axis=0)
            px = int(np.clip(centroid_uv[0] * (w - 1), 0, w - 1))
            py = int(np.clip((1.0 - centroid_uv[1]) * (h - 1), 0, h - 1))
            pixel = tex[py, px]
            colors[i, :3] = pixel[:3] / 255.0
            colors[i, 3] = pixel[3] / 255.0 if len(pixel) > 3 else 1.0
        return colors

    if type(vis).__name__ == "ColorVisuals":
        fc = getattr(vis, "face_colors", None)
        if fc is not None and len(fc) == len(mesh.faces):
            return fc.astype(np.float64) / 255.0

    return None


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    try:
        import trimesh  # noqa: F401  # pylint: disable=unused-import
    except ImportError as error:
        raise RuntimeError(_TRIMESH_HINT) from error

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image

    from vendor.media_toolkit.renderers import meta_block

    max_pages = min(int(opts.get("max_pages", len(VIEWS))), len(VIEWS))
    meshes, total_verts, total_faces = _load_scene(path)

    all_verts = []
    all_faces = []
    all_colors = []
    offset = 0

    for m in meshes:
        fc = _sample_face_colors(m, np)
        all_verts.append(m.vertices)
        all_faces.append(m.faces + offset)
        if fc is not None:
            all_colors.append(fc)
        else:
            default = np.full(
                (len(m.faces), 4),
                [0.357, 0.608, 0.835, 0.85],
            )
            all_colors.append(default)
        offset += len(m.vertices)

    vertices = np.vstack(all_verts)
    faces = np.vstack(all_faces)
    face_colors = np.vstack(all_colors)
    has_texture = any(_sample_face_colors(m, np) is not None for m in meshes)

    if len(faces) > MAX_MPL_FACES:
        idx = np.random.default_rng(42).choice(
            len(faces),
            MAX_MPL_FACES,
            replace=False,
        )
        faces = faces[idx]
        face_colors = face_colors[idx]

    center = vertices.mean(axis=0)
    vertices = vertices - center
    scale = np.abs(vertices).max()
    if scale > 0:
        vertices = vertices / scale

    info = f"{total_verts} vertices, {total_faces} faces"
    content: list[dict[str, Any]] = [
        meta_block("model3d", max_pages, list(range(1, max_pages + 1))),
    ]
    for page, (title, elev, azim) in enumerate(VIEWS[:max_pages], start=1):
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection="3d")

        face_verts = vertices[faces]
        poly = Poly3DCollection(face_verts, alpha=0.85)
        if has_texture:
            poly.set_facecolor(face_colors[:, :3])
            poly.set_edgecolor("none")
        else:
            poly.set_facecolor("#5B9BD5")
            poly.set_edgecolor("#2F528F")
            poly.set_linewidth(0.1)
        ax.add_collection3d(poly)

        lim = 1.1
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_zlim(-lim, lim)
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(
            f"{os.path.basename(path)} — {title}",
            fontsize=12,
            pad=10,
        )
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.text2D(
            0.02,
            0.02,
            info,
            transform=ax.transAxes,
            fontsize=8,
            color="gray",
        )

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=150,
            bbox_inches="tight",
            pad_inches=0.2,
        )
        plt.close(fig)
        buf.seek(0)
        content.append(
            {
                "type": "image",
                "image": Image.open(buf),
                "page": page,
                "label": f"[{title}] {info}",
            },
        )

    content.append({"type": "full_text", "text": f"[3D model] {info}"})
    return content
