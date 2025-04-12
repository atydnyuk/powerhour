# Power Hour Generator

A Python script that automatically generates "power hour" videos by combining multiple video clips with transitions and overlaid information.

## What is a Power Hour?

A power hour is a compilation video that consists of 60 one-minute segments from different videos, typically music videos. Each segment is accompanied by a transition effect and numbered to keep track of progress.

## Features

- Combines multiple video clips into a single hour-long video
- Adds numbered transitions between clips
- Displays clip numbers and video names as overlays
- Supports custom start times for video clips via configuration
- Configurable video dimensions and output format
- Fade effects between transitions

## Requirements

- Python 3.x
- moviepy
- A collection of source videos
- A transition video clip

## Installation

1. Clone this repository
2. Install the required dependencies:
```bash
pip install moviepy
```

## Usage

Basic usage with default settings:
```bash
python power_hour_generator.py
```

Advanced usage with custom parameters:
```bash
python power_hour_generator.py --source videos_folder --config config.cfg --transition my_transition.mp4 --out final_video.avi --width 1920 --height 1080
```

### Command Line Arguments

- `--source`: Path to directory containing source videos (default: 'source_video')
- `--config`: Path to configuration file (default: 'power_hour.cfg')
- `--transition`: Path to transition video file (default: 'transition.mp4')
- `--out`: Output file path (default: 'out.avi')
- `--width`: Video width in pixels (default: 1920)
- `--height`: Video height in pixels (default: 1080)
- `--delimiter`: Configuration file delimiter (default: '|')

### Configuration File Format

The configuration file allows you to specify custom start times for video clips. Each line should contain:
