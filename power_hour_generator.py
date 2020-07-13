from os import listdir

import argparse
from moviepy import editor

DEFAULT_SOURCE_FOLDER = 'source_video'
DEFAULT_CONFIG_PATH = 'power_hour.cfg'
DEFAULT_TRANSITION_FILE_PATH = 'transition.avi'
DEFAULT_OUTFILE = 'out.avi'
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_CONFIG_DELIMITER = '|'


class PowerHourGenerator(object):
    def __init__(self, config_path, source_folder, transition_path, outfile, width, height, delimiter):
        self.config_path = config_path
        self.source_folder = source_folder
        self.transition_path = transition_path
        self.outfile = outfile
        self.width = width
        self.height = height
        self.delimiter = delimiter
        
    def init_config(self):
        config = {}
        with open(self.config_path, 'r') as file:
            for config_row in file:
                # allow comments
                if config_row[0] == '#':
                    continue
                config_row_array = config_row.split(self.delimiter)
                video_name = config_row_array[0]
                start_second = config_row_array[1]
        return config

    def run(self):
        video_to_config_map = {}
        if self.config_path:
            video_to_config_map = self.init_config()

        # the number overlay for the initial transition  
        first_text_clip_part = editor.TextClip(str(1), color='white', fontsize=36).set_position((10, 10))
        first_text_clip = first_text_clip_part.on_color(size=(50, 50), color=(0,0,0), pos=(10,10), col_opacity=0.6)

        transition_path = '{}'.format(DEFAULT_TRANSITION_FILE_PATH)
        transition_clip = editor.VideoFileClip(transition_path)
        transition_clip = transition_clip.resize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)

        if transition_clip.duration > 6:
            print 'Your transition is longer than 6 seconds. For best results, trim the clip to 5-6 seconds.'

        padding = 3
        list_of_clips = []
        for i, clip_name in enumerate(listdir(DEFAULT_SOURCE_FOLDER)):
            print 'Processing: {} -- {}'.format(i, clip_name)
            clip_path = '{}/{}'.format(self.source_folder, clip_name)
            raw_clip = editor.VideoFileClip(clip_path)

            # by default, start one third of the way into the clip
            # this works reasonably well for music videos
            start_point = raw_clip.duration / 3

            # if there is a specific starting point configured, use that instead
            if clip_name in video_to_config_map:
                if CONFIG_DELIMITER in clip_name:
                    print 'Video {} contains config delimiter character {}. To correct, either rename video or change delimiter'.format(
                        clip_name,
                        CONFIG_DELIMITER
                    )
                    raise RuntimeError('Video name contains config delimiter character.')
                start_point = video_to_config_map[clip_name]

            # these are always going to be 60 secs long - length of transition so that everything takes exactly an hour
            clip = editor.VideoFileClip(clip_path).subclip(t_start=start_point, t_end=start_point + 60 - transition_clip.duration)
            clip = clip.resize(width=self.width, height=self.height)
            list_of_clips.append(clip)

        list_with_transitions = []

        for i, video in enumerate(list_of_clips):
            # create a new text clip with the current number on each loop
            text_clip = editor.TextClip(str(i+1), color='white', fontsize=36).on_color(
                size=(50, 50), color=(0,0,0), pos=(0,0), col_opacity=0.6
            ).set_position(('left', 'top'))

            # TODO: figure out why I have to re-instantiate the transition clip each time for this to work
            transition_clip = editor.VideoFileClip(transition_path)
            transition_clip = transition_clip.resize(width=self.width, height=self.height)
            transition_clip_with_number = editor.CompositeVideoClip([transition_clip, text_clip])
            transition_clip_with_number.duration = transition_clip.duration
            list_with_transitions.append(transition_clip_with_number)

            # render the video with the number
            video_clip_with_number = editor.CompositeVideoClip([video, text_clip])
            video_clip_with_number.duration = video.duration
            video_clip_with_number = video_clip_with_number.resize(width=self.width, height=self.height)
            list_with_transitions.append(video_clip_with_number.fadeout(padding).audio_fadeout(padding))
        final_video = editor.concatenate_videoclips(list_with_transitions, padding=0, method='compose')
        final_video.write_videofile(DEFAULT_OUTFILE, fps=24, codec='libx264')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--source',
        dest='source',
        help='Path to directory with videos (default: {})'.format(DEFAULT_SOURCE_FOLDER),
        default=DEFAULT_SOURCE_FOLDER
    )
    parser.add_argument(
        '--config',
        dest='config',
        help='Path to config (default: {})'.format(DEFAULT_CONFIG_PATH),
        default=DEFAULT_CONFIG_PATH
    )
    parser.add_argument(
        '--transition',
        dest='transition',
        help='Path to transition file (default: {})'.format(DEFAULT_TRANSITION_FILE_PATH),
        default=DEFAULT_TRANSITION_FILE_PATH
    )
    parser.add_argument(
        '--out',
        dest='out',
        help='Path to output file (default: {})'.format(DEFAULT_OUTFILE),
        default=DEFAULT_OUTFILE
    )
    parser.add_argument(
        '--width',
        dest='width',
        help='Video width (default: {})'.format(DEFAULT_WIDTH),
        default=DEFAULT_WIDTH
    )
    parser.add_argument(
        '--height',
        dest='height',
        help='Video height (default: {})'.format(DEFAULT_HEIGHT),
        default=DEFAULT_HEIGHT
    )
    parser.add_argument(
        '--delimiter',
        dest='delimiter',
        help='Config delimiter (default: {})'.format(DEFAULT_CONFIG_DELIMITER),
        default=DEFAULT_CONFIG_DELIMITER
    )
    args = parser.parse_args()

    job = PowerHourGenerator(
        args.config,
        args.source,
        args.transition,
        args.out,
        args.width,
        args.height,
        args.delimiter
    )
    job.run()

        
if __name__ == '__main__':
    main()
