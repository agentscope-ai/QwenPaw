# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Qwen3-VL-Embedding model implementation.

This file is adapted from the official Qwen3-VL-Embedding repository:
https://github.com/QwenLM/Qwen3-VL-Embedding

Licensed under Apache 2.0 License.
"""
import logging
import os
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers.models.qwen3_vl.modeling_qwen3_vl import (
    Qwen3VLPreTrainedModel,
    Qwen3VLModel,
    Qwen3VLConfig,
)
from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor
from transformers.modeling_outputs import ModelOutput
from transformers.processing_utils import Unpack
from transformers.utils import TransformersKwargs
from transformers.cache_utils import Cache
from qwen_vl_utils.vision_process import process_vision_info

logger = logging.getLogger(__name__)

# Constants for configuration
MAX_LENGTH = 8192
IMAGE_BASE_FACTOR = 16
IMAGE_FACTOR = IMAGE_BASE_FACTOR * 2
MIN_PIXELS = 4 * IMAGE_FACTOR * IMAGE_FACTOR
MAX_PIXELS = 1800 * IMAGE_FACTOR * IMAGE_FACTOR
FPS = 1
MAX_FRAMES = 64
FRAME_MAX_PIXELS = 768 * IMAGE_FACTOR * IMAGE_FACTOR
MAX_TOTAL_PIXELS = 10 * FRAME_MAX_PIXELS
PAD_TOKEN = "<|endoftext|>"


@dataclass
class Qwen3VLForEmbeddingOutput(ModelOutput):
    """Output structure for embeddings."""
    last_hidden_state: Optional[torch.FloatTensor] = None
    attention_mask: Optional[torch.Tensor] = None


class Qwen3VLForEmbedding(Qwen3VLPreTrainedModel):
    """Model class to compute embeddings."""
    _checkpoint_conversion_mapping = {}
    accepts_loss_kwargs = False
    config: Qwen3VLConfig

    def __init__(self, config):
        super().__init__(config)
        self.model = Qwen3VLModel(config)
        self.post_init()

    def get_input_embeddings(self):
        return self.model.get_input_embeddings()

    def set_input_embeddings(self, value):
        self.model.set_input_embeddings(value)

    def set_decoder(self, decoder):
        self.model.set_decoder(decoder)

    def get_decoder(self):
        return self.model.get_decoder()

    def get_video_features(
        self,
        pixel_values_videos: torch.FloatTensor,
        video_grid_thw: Optional[torch.LongTensor] = None,
    ):
        return self.model.get_video_features(
            pixel_values_videos, video_grid_thw
        )

    def get_image_features(
        self,
        pixel_values: torch.FloatTensor,
        image_grid_thw: Optional[torch.LongTensor] = None,
    ):
        return self.model.get_image_features(pixel_values, image_grid_thw)

    @property
    def language_model(self):
        return self.model.language_model

    @property
    def visual(self):
        return self.model.visual

    def forward(  # pylint: disable=unused-argument
        self,
        input_ids: torch.LongTensor = None,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        past_key_values: Optional[Cache] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        pixel_values: Optional[torch.Tensor] = None,
        pixel_values_videos: Optional[torch.FloatTensor] = None,
        image_grid_thw: Optional[torch.LongTensor] = None,
        video_grid_thw: Optional[torch.LongTensor] = None,
        cache_position: Optional[torch.LongTensor] = None,
        logits_to_keep: Union[int, torch.Tensor] = 0,
        **kwargs: Unpack[TransformersKwargs],
    ) -> Union[tuple, Qwen3VLForEmbeddingOutput]:
        outputs = self.model(
            input_ids=input_ids,
            pixel_values=pixel_values,
            pixel_values_videos=pixel_values_videos,
            image_grid_thw=image_grid_thw,
            video_grid_thw=video_grid_thw,
            position_ids=position_ids,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            inputs_embeds=inputs_embeds,
            cache_position=cache_position,
            **kwargs,
        )
        return Qwen3VLForEmbeddingOutput(
            last_hidden_state=outputs.last_hidden_state,
            attention_mask=attention_mask,
        )


def sample_frames(
    frames: List[Union[str, Image.Image]],
    max_segments: int,
) -> List[Union[str, Image.Image]]:
    duration = len(frames)
    if duration <= max_segments:
        return frames

    frame_id_array = np.linspace(0, duration - 1, max_segments, dtype=int)
    frame_id_list = frame_id_array.tolist()
    sampled_frames = [frames[frame_idx] for frame_idx in frame_id_list]
    return sampled_frames


def is_image_path(path: str) -> bool:
    image_extensions = {
        '.jpg', '.jpeg', '.png', '.gif',
        '.bmp', '.webp', '.tiff', '.svg',
    }

    if path.startswith(('http://', 'https://')):
        parsed_url = urlparse(path)
        clean_path = parsed_url.path
    else:
        clean_path = path

    _, ext = os.path.splitext(clean_path.lower())
    return ext in image_extensions


def is_video_input(video) -> bool:
    if isinstance(video, str):
        return True

    if isinstance(video, list) and len(video) > 0:
        first_elem = video[0]
        if isinstance(first_elem, Image.Image):
            return True
        if isinstance(first_elem, str):
            return is_image_path(first_elem)

    return False


class Qwen3VLEmbedder:
    """Embedder class for processing inputs and generating embeddings."""

    def __init__(
        self,
        model_name_or_path: str,
        max_length: int = MAX_LENGTH,
        min_pixels: int = MIN_PIXELS,
        max_pixels: int = MAX_PIXELS,
        total_pixels: int = MAX_TOTAL_PIXELS,
        fps: float = FPS,
        max_frames: int = MAX_FRAMES,
        default_instruction: str = "Represent the user's input.",
        device: Optional[str] = None,
        **kwargs
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.max_length = max_length
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.total_pixels = total_pixels
        self.fps = fps
        self.max_frames = max_frames
        self.default_instruction = default_instruction

        self.model = Qwen3VLForEmbedding.from_pretrained(
            model_name_or_path, trust_remote_code=True, **kwargs
        ).to(self.device)
        self.processor = Qwen3VLProcessor.from_pretrained(
            model_name_or_path, padding_side='right'
        )
        self.model.eval()

    @torch.no_grad()
    def forward(self, inputs: Dict[str, Any]) -> Dict[str, torch.Tensor]:
        outputs = self.model(**inputs)
        return {
            'last_hidden_state': outputs.last_hidden_state,
            'attention_mask': inputs.get('attention_mask')
        }

    def _truncate_tokens(
        self,
        token_ids: List[int],
        max_length: int,
    ) -> List[int]:
        if len(token_ids) <= max_length:
            return token_ids

        special_token_ids = set(
            self.processor.tokenizer.all_special_ids
        )
        num_special = sum(
            1 for token_idx in token_ids
            if token_idx in special_token_ids
        )
        num_non_special_to_keep = max_length - num_special

        final_token_ids = []
        non_special_kept_count = 0
        for token_idx in token_ids:
            if token_idx in special_token_ids:
                final_token_ids.append(token_idx)
            elif non_special_kept_count < num_non_special_to_keep:
                final_token_ids.append(token_idx)
                non_special_kept_count += 1
        return final_token_ids

    def format_model_input(  # noqa: E501  pylint: disable=too-many-branches,too-many-statements
        self,
        text: Optional[Union[List[str], str]] = None,
        image: Optional[
            Union[List[Union[str, Image.Image]], str, Image.Image]
        ] = None,
        video: Optional[
            Union[
                List[Union[str, List[Union[str, Image.Image]]]],
                str,
                List[Union[str, Image.Image]],
            ]
        ] = None,
        instruction: Optional[str] = None,
        fps: Optional[float] = None,
        max_frames: Optional[int] = None,
    ) -> List[Dict]:

        if instruction:
            instruction = instruction.strip()
            if instruction and not unicodedata.category(instruction[-1]).startswith('P'):
                instruction = instruction + '.'

        content = []
        conversation = [
            {"role": "system", "content": [
                {"type": "text", "text": instruction or self.default_instruction}]},
            {"role": "user", "content": content}
        ]

        if text is None:
            texts = []
        elif isinstance(text, str):
            texts = [text]
        else:
            texts = text

        if image is None:
            images = []
        elif not isinstance(image, list):
            images = [image]
        else:
            images = image

        if video is None:
            videos = []
        elif is_video_input(video):
            videos = [video]
        else:
            videos = video

        if not texts and not images and not videos:
            content.append({'type': 'text', 'text': "NULL"})
            return conversation

        for vid in videos:
            video_content = None
            video_kwargs = {'total_pixels': self.total_pixels}

            if isinstance(vid, list):
                video_content = vid
                if self.max_frames is not None:
                    video_content = sample_frames(
                        video_content, self.max_frames)
                video_content = [
                    ('file://' + ele if isinstance(ele, str) else ele)
                    for ele in video_content
                ]
            elif isinstance(vid, str):
                video_content = vid if vid.startswith(
                    ('http://', 'https://')) else 'file://' + vid
                video_kwargs = {
                    'fps': fps or self.fps,
                    'max_frames': max_frames or self.max_frames,
                }
            else:
                raise TypeError(f"Unrecognized video type: {type(vid)}")

            if video_content:
                content.append({
                    'type': 'video',
                    'video': video_content,
                    **video_kwargs
                })

        for img in images:
            image_content = None

            if isinstance(img, Image.Image):
                image_content = img
            elif isinstance(img, str):
                image_content = img if img.startswith(
                    ('http://', 'https://')) else 'file://' + img
            else:
                raise TypeError(f"Unrecognized image type: {type(img)}")

            if image_content:
                content.append({
                    'type': 'image',
                    'image': image_content,
                    "min_pixels": self.min_pixels,
                    "max_pixels": self.max_pixels
                })

        for txt in texts:
            content.append({'type': 'text', 'text': txt})

        return conversation

    def _preprocess_inputs(self, conversations: List[List[Dict]]) -> Dict[str, torch.Tensor]:
        text = self.processor.apply_chat_template(
            conversations, add_generation_prompt=True, tokenize=False
        )

        try:
            images, video_inputs, video_kwargs = process_vision_info(
                conversations, image_patch_size=16,
                return_video_metadata=True, return_video_kwargs=True
            )
        except Exception as e:
            logger.error(f"Error in processing vision info: {e}")
            images = None
            video_inputs = None
            video_kwargs = {'do_sample_frames': False}
            text = self.processor.apply_chat_template(
                [{'role': 'user', 'content': [{'type': 'text', 'text': 'NULL'}]}],
                add_generation_prompt=True, tokenize=False
            )

        if video_inputs is not None:
            videos, video_metadata = zip(*video_inputs)
            videos = list(videos)
            video_metadata = list(video_metadata)
        else:
            videos, video_metadata = None, None

        inputs = self.processor(
            text=text, images=images, videos=videos, video_metadata=video_metadata,
            truncation=True, max_length=self.max_length, padding=True,
            do_resize=False, return_tensors='pt', **video_kwargs
        )
        return inputs

    @staticmethod
    def _pooling_last(hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        flipped_tensor = attention_mask.flip(dims=[1])
        last_one_positions = flipped_tensor.argmax(dim=1)
        col = attention_mask.shape[1] - last_one_positions - 1
        row = torch.arange(hidden_state.shape[0], device=hidden_state.device)
        return hidden_state[row, col]

    def process(self, inputs: List[Dict[str, Any]], normalize: bool = True) -> torch.Tensor:
        """Process inputs to generate normalized embeddings.

        Args:
            inputs: List of dicts, each containing text/image/video/instruction
            normalize: Whether to L2 normalize embeddings

        Returns:
            Tensor of shape (batch_size, hidden_dim) containing embeddings
        """
        conversations = [self.format_model_input(
            text=ele.get('text'),
            image=ele.get('image'),
            video=ele.get('video'),
            instruction=ele.get('instruction'),
            fps=ele.get('fps'),
            max_frames=ele.get('max_frames')
        ) for ele in inputs]

        processed_inputs = self._preprocess_inputs(conversations)
        processed_inputs = {
            k: v.to(self.model.device) for k, v in processed_inputs.items()
        }

        outputs = self.forward(processed_inputs)
        embeddings = self._pooling_last(
            outputs['last_hidden_state'], outputs['attention_mask'])

        if normalize:
            embeddings = F.normalize(embeddings, p=2, dim=-1)

        return embeddings
