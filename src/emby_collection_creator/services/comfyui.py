"""ComfyUI API service for image generation with Flux."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx
from attrs import define, field
from PIL import Image, ImageDraw, ImageFont


@define
class ComfyUIService:
    """Client for ComfyUI API."""

    base_url: str = "http://127.0.0.1:8080"
    output_dir: Path = field(factory=lambda: Path("./artwork/generated"))
    _client: httpx.AsyncClient | None = None

    def __attrs_post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=300.0,  # Long timeout for image generation
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def is_available(self) -> bool:
        """Check if ComfyUI is running."""
        try:
            client = await self._get_client()
            resp = await client.get("/system_stats")
            return resp.status_code == 200
        except httpx.ConnectError:
            return False

    def add_title_overlay(self, image_path: Path, title: str) -> None:
        """Add a title overlay to the bottom of an image."""
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Calculate font size based on image width (roughly 1/12th of width)
        target_font_size = img.width // 12
        font = None

        # Try to load a nice font, fall back to default
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, target_font_size)
                break
            except (OSError, IOError):
                continue

        if font is None:
            font = ImageFont.load_default()

        # Get text bounding box
        bbox = draw.textbbox((0, 0), title, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Position text at bottom center with padding
        padding = 40
        x = (img.width - text_width) // 2
        y = img.height - text_height - padding

        # Draw semi-transparent background bar
        bar_padding = 20
        bar_top = y - bar_padding
        bar_bottom = img.height
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            [(0, bar_top), (img.width, bar_bottom)],
            fill=(0, 0, 0, 180),
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay)

        # Draw text with shadow for depth
        draw = ImageDraw.Draw(img)
        shadow_offset = 3
        draw.text((x + shadow_offset, y + shadow_offset), title, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), title, font=font, fill=(255, 255, 255, 255))

        # Save back
        img.convert("RGB").save(image_path, "PNG")

    async def queue_prompt(self, workflow: dict) -> str:
        """Queue a workflow and return the prompt ID."""
        client = await self._get_client()
        client_id = str(uuid.uuid4())

        resp = await client.post(
            "/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    async def get_history(self, prompt_id: str) -> dict | None:
        """Get the execution history for a prompt."""
        client = await self._get_client()
        resp = await client.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        history = resp.json()
        return history.get(prompt_id)

    async def wait_for_completion(
        self, prompt_id: str, poll_interval: float = 1.0, timeout: float = 300.0
    ) -> dict:
        """Wait for a prompt to complete and return the output info."""
        elapsed = 0.0
        while elapsed < timeout:
            history = await self.get_history(prompt_id)
            if history and history.get("outputs"):
                return history
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """Download an image from ComfyUI."""
        client = await self._get_client()
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder
        resp = await client.get("/view", params=params)
        resp.raise_for_status()
        return resp.content

    def build_flux_workflow(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        guidance: float = 3.5,
        seed: int | None = None,
    ) -> dict:
        """Build a Flux Dev workflow for poster generation."""
        if seed is None:
            seed = uuid.uuid4().int & 0xFFFFFFFF

        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "flux1-dev-fp8.safetensors"
                }
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["1", 1]
                }
            },
            "3": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                }
            },
            "4": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["8", 0],
                    "negative": ["5", 0],
                    "latent_image": ["3", 0]
                }
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "",
                    "clip": ["1", 1]
                }
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["4", 0],
                    "vae": ["1", 2]
                }
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "flux_poster",
                    "images": ["6", 0]
                }
            },
            "8": {
                "class_type": "FluxGuidance",
                "inputs": {
                    "guidance": guidance,
                    "conditioning": ["2", 0]
                }
            }
        }

    async def generate_poster(
        self,
        prompt: str,
        collection_name: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        guidance: float = 3.5,
        seed: int | None = None,
        title: str | None = None,
    ) -> Path:
        """Generate a poster and save it locally."""
        workflow = self.build_flux_workflow(
            prompt=prompt,
            width=width,
            height=height,
            steps=steps,
            guidance=guidance,
            seed=seed,
        )

        prompt_id = await self.queue_prompt(workflow)
        history = await self.wait_for_completion(prompt_id)

        # Find the output image
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                image_info = node_output["images"][0]
                filename = image_info["filename"]
                subfolder = image_info.get("subfolder", "")

                image_data = await self.get_image(filename, subfolder)

                # Save locally with collection name
                safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in collection_name)
                local_filename = f"{safe_name}_{prompt_id[:8]}.png"
                local_path = self.output_dir / local_filename
                local_path.write_bytes(image_data)

                # Add title overlay if provided
                if title:
                    self.add_title_overlay(local_path, title)

                return local_path

        raise RuntimeError("No image output found in workflow result")

    async def generate_multiple(
        self,
        prompt: str,
        collection_name: str,
        count: int = 4,
        width: int = 768,
        height: int = 1152,
        steps: int = 20,
        guidance: float = 3.5,
    ) -> list[Path]:
        """Generate multiple poster variations."""
        paths = []
        for i in range(count):
            path = await self.generate_poster(
                prompt=prompt,
                collection_name=collection_name,
                width=width,
                height=height,
                steps=steps,
                guidance=guidance,
            )
            paths.append(path)
        return paths
