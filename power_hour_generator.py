import os
import json
import argparse
import tempfile
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont

DEFAULT_SOURCE_FOLDER = 'source_video'
DEFAULT_CONFIG_PATH = 'power_hour.cfg'
DEFAULT_TRANSITION_FILE_PATH = 'transition.mp4'
DEFAULT_OUTFILE = 'out.mp4'
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_CONFIG_DELIMITER = '|'
DEFAULT_WORKERS = 8

_FONT_CANDIDATES = [
    '/Library/Fonts/Arial Unicode.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]
UNICODE_FONT = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)


def ffprobe_duration(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)['format']['duration'])


def render_overlay(text, fontsize=36, padding=8, max_width=None):
    """Render text on a semi-transparent dark background; return an RGBA PIL Image."""
    try:
        font = ImageFont.truetype(UNICODE_FONT, fontsize) if UNICODE_FONT else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Measure from (0,0) so we get the true pixel extents including internal
    # font leading. Drawing at (padding, padding) without this offset causes
    # the text to render below its measured bbox, clipping the bottom ~15%.
    tmp = Image.new('RGBA', (4000, fontsize * 3))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w = min(text_w + padding * 2, max_width) if max_width else text_w + padding * 2
    img_h = text_h + padding * 2

    img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (img_w - 1, img_h - 1)], fill=(0, 0, 0, 153))  # 60% opacity
    # Offset compensates for bbox[0]/bbox[1] so rendered pixels land at (padding, padding)
    draw.text((padding - bbox[0], padding - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    return img


class PowerHourGenerator:
    def __init__(self, config_path, source_folder, transition_path, outfile,
                 width, height, delimiter, workers, limit=None, hw_accel=True):
        self.config_path = config_path
        self.source_folder = source_folder
        self.transition_path = transition_path
        self.outfile = outfile
        self.width = width
        self.height = height
        self.delimiter = delimiter
        self.workers = workers
        self.limit = limit
        self.hw_accel = hw_accel

    def _video_encoder_args(self):
        # -bf 0 disables B-frames so DTS==PTS on every frame, which prevents
        # VLC "buffer deadlock" errors at clip boundaries after stream-copy concat.
        if self.hw_accel:
            return ['-c:v', 'h264_videotoolbox', '-q:v', '65', '-realtime', '0',
                    '-bf', '0']
        return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-bf', '0']

    def init_config(self):
        config = {}
        with open(self.config_path, 'r') as fh:
            for row in fh:
                row = row.strip()
                if not row or row.startswith('#'):
                    continue
                parts = row.split(self.delimiter)
                if len(parts) >= 2:
                    config[parts[0]] = float(parts[1])
        return config

    def _make_overlays(self, clip_num, video_stem, temp_dir):
        """Render number and name overlay PNGs. Returns (num_png, name_png) paths."""
        num_img = render_overlay(str(clip_num))
        name_img = render_overlay(video_stem, max_width=self.width - 20)

        num_png = os.path.join(temp_dir, f'num_{clip_num:03d}.png')
        name_png = os.path.join(temp_dir, f'name_{clip_num:03d}.png')
        num_img.save(num_png)
        name_img.save(name_png)
        return num_png, name_png

    def _encode_clip(self, clip_path, clip_num, start_time, clip_duration,
                     num_png, name_png, temp_dir):
        out = os.path.join(temp_dir, f'clip_{clip_num:03d}.mp4')
        fade_start = clip_duration - 3

        # Build filter graph:
        #   scale + pad → overlay number (always) → overlay name (after 30s) → fade
        filter_complex = (
            f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fade=type=out:start_time={fade_start:.3f}:duration=3[base];"
            f"[base][1:v]overlay=10:10[v1];"
            f"[v1][2:v]overlay=W-w-10:10:enable='gte(t,30)'[v];"
            f"[0:a]afade=type=out:start_time={fade_start:.3f}:duration=3[a]"
        )
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'warning',
            '-ss', f'{start_time:.3f}', '-i', clip_path,
            '-i', num_png, '-i', name_png,
            '-t', f'{clip_duration:.3f}',
            '-filter_complex', filter_complex,
            '-map', '[v]', '-map', '[a]',
            *self._video_encoder_args(),
            '-c:a', 'aac', '-b:a', '192k', '-ar', '44100',
            '-r', '24', out,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f'clip {clip_num} failed:\n{r.stderr[-800:]}')
        return out

    def _encode_transition(self, clip_num, num_png, temp_dir):
        out = os.path.join(temp_dir, f'transition_{clip_num:03d}.mp4')
        filter_complex = (
            f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black[base];"
            f"[base][1:v]overlay=10:10[v]"
        )
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'warning',
            '-i', self.transition_path,
            '-i', num_png,
            '-filter_complex', filter_complex,
            '-map', '[v]', '-map', '0:a',
            *self._video_encoder_args(),
            '-c:a', 'aac', '-b:a', '192k', '-ar', '44100',
            '-r', '24', out,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f'transition {clip_num} failed:\n{r.stderr[-800:]}')
        return out

    def run(self):
        temp_dir = tempfile.mkdtemp(prefix='powerhour_')
        try:
            self._run(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run(self, temp_dir):
        transition_duration = ffprobe_duration(self.transition_path)
        if transition_duration > 6:
            print(f'Warning: transition is {transition_duration:.1f}s (>6s recommended)')
        clip_duration = 60.0 - transition_duration

        config = self.init_config() if self.config_path else {}

        all_names = sorted(f for f in os.listdir(self.source_folder) if not f.startswith('.'))
        clip_names = all_names[:self.limit] if self.limit else all_names
        print(f'Found {len(clip_names)} clips (of {len(all_names)} total). '
              f'Encoding with {self.workers} parallel workers...')

        # Gather clip metadata (ffprobe is fast; do sequentially)
        clip_infos = []
        for clip_name in clip_names:
            clip_path = os.path.join(self.source_folder, clip_name)
            duration = ffprobe_duration(clip_path)
            start_time = config.get(clip_name, duration / 3)
            clip_infos.append((clip_name, clip_path, start_time))

        # Pre-render all overlay PNGs (fast; avoids any race conditions in threads)
        overlay_pngs = {}
        for i, (_, clip_path, _) in enumerate(clip_infos):
            num = i + 1
            overlay_pngs[num] = self._make_overlays(num, Path(clip_path).stem, temp_dir)

        # Submit clips AND transitions as independent tasks for maximum parallelism
        # (transitions are short ~8s encodes; keeping them separate lets the pool
        #  overlap them with the longer ~20s clip encodes)
        futures = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for i, (clip_name, clip_path, start_time) in enumerate(clip_infos):
                num = i + 1
                num_png, name_png = overlay_pngs[num]

                f = pool.submit(self._encode_clip, clip_path, num, start_time,
                                clip_duration, num_png, name_png, temp_dir)
                futures[f] = f'clip {num} ({clip_name})'

                f = pool.submit(self._encode_transition, num, num_png, temp_dir)
                futures[f] = f'transition {num}'

            done = 0
            total = len(futures)
            for future in as_completed(futures):
                label = futures[future]
                done += 1
                try:
                    future.result()
                    print(f'[{done}/{total}] Done: {label}')
                except Exception as e:
                    print(f'[{done}/{total}] FAILED: {label}: {e}')
                    raise

        # Build concat list and stream-copy into final output (no re-encode)
        concat_file = os.path.join(temp_dir, 'concat.txt')
        with open(concat_file, 'w') as fh:
            for i in range(len(clip_infos)):
                num = i + 1
                fh.write(f"file '{temp_dir}/transition_{num:03d}.mp4'\n")
                fh.write(f"file '{temp_dir}/clip_{num:03d}.mp4'\n")

        print('Concatenating final video...')
        r = subprocess.run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',
            self.outfile,
        ])
        if r.returncode != 0:
            raise RuntimeError('Final concat failed')
        print(f'Done! Output: {self.outfile}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', dest='source', default=DEFAULT_SOURCE_FOLDER,
                        help=f'Source video folder (default: {DEFAULT_SOURCE_FOLDER})')
    parser.add_argument('--config', dest='config', default=DEFAULT_CONFIG_PATH,
                        help=f'Config file path (default: {DEFAULT_CONFIG_PATH})')
    parser.add_argument('--transition', dest='transition', default=DEFAULT_TRANSITION_FILE_PATH,
                        help=f'Transition clip (default: {DEFAULT_TRANSITION_FILE_PATH})')
    parser.add_argument('--out', dest='out', default=DEFAULT_OUTFILE,
                        help=f'Output file (default: {DEFAULT_OUTFILE})')
    parser.add_argument('--width', dest='width', type=int, default=DEFAULT_WIDTH,
                        help=f'Video width (default: {DEFAULT_WIDTH})')
    parser.add_argument('--height', dest='height', type=int, default=DEFAULT_HEIGHT,
                        help=f'Video height (default: {DEFAULT_HEIGHT})')
    parser.add_argument('--delimiter', dest='delimiter', default=DEFAULT_CONFIG_DELIMITER,
                        help=f'Config delimiter (default: {DEFAULT_CONFIG_DELIMITER})')
    parser.add_argument('--workers', dest='workers', type=int, default=DEFAULT_WORKERS,
                        help=f'Parallel encoding workers (default: {DEFAULT_WORKERS})')
    parser.add_argument('--limit', dest='limit', type=int, default=None,
                        help='Only process first N clips (useful for testing)')
    parser.add_argument('--no-hw', dest='no_hw', action='store_true',
                        help='Disable hardware (VideoToolbox) encoding, use libx264 instead')
    parser.add_argument('--subdir', dest='subdir', default=None,
                        help='Subdirectory inside source folder, e.g. "my_playlist" '
                             '→ source_video/my_playlist/')
    args = parser.parse_args()

    source = os.path.join(args.source, args.subdir) if args.subdir else args.source

    PowerHourGenerator(
        args.config, source, args.transition, args.out,
        args.width, args.height, args.delimiter, args.workers, args.limit,
        hw_accel=not args.no_hw,
    ).run()


if __name__ == '__main__':
    main()
