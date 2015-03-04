import ImageDraw, ImageFont
import os
from collections import defaultdict
from pylons import g

from r2.lib.media import url_to_image
from r2.models import Frontpage
from r2.models.gold import GoldGoal
from r2.models.wiki import WikiPageIniItem
from reddit_adzerk import adzerk_api

default_font_path = "r2/public/static/fonts/"
default_font = "Georgia.ttf"
output_path = "r2/public/static/"

class DynamicCreativeWiki(WikiPageIniItem):
    @classmethod
    def _get_wiki_config(self):
        return Frontpage, g.wiki_page_dynamic_gold_ad

    def __init__(self, id, creative_id=None, item_type=None, image_url=None,
            x_offset=0, x_offset_len=300, y_offset=0, y_offset_len=250,
            font="Georgia.ttf", font_color="#9A7D2E", font_size=16,
            align="center", min_percentage=0, max_percentage=100, **kwargs):
        """reads in config for dynamic gold ad. each creative should have
        sections with item_types of 'progress_bar' and 'bg_image'.
        'font_prefs' is optional. all section names should be unique.

        available options for each item_type (*required):
        [progress_bar]*: creative_id*, item_type*, image_url*,
            x_offset, y_offset
        [bg_image]*: creative_id*, item_type*, image_url*,
            min_percentage, max_percentage, x_offset, y_offset
        [font_prefs]: creative_id*, item_type*, align,
            font, font_color, font_size,
            x_offset, x_offset_len, y_offset, y_offset_len
        """
        self.is_enabled = True
        self.id = id
        self.creative_id = creative_id
        self.item_type = item_type
        self.offset = (int(x_offset), int(y_offset))

        if not creative_id:
            g.log.error("DynamicCreativeWiki: No creative_id for [%s]" % id)
        if not item_type or item_type not in ('progress_bar', 'bg_image', 'font_prefs'):
            g.log.error("DynamicCreativeWiki: Invalid item_type %s for [%s]"
                % (item_type, self.id))

        if item_type == 'font_prefs':
            self.set_font_props(font, font_color, int(font_size), align.lower(),
                x_offset_len, y_offset_len)
        elif item_type == 'bg_image':
            self.set_bg_image_props(image_url,
                int(min_percentage), int(max_percentage))
        elif item_type == 'progress_bar':
            self.image_url = image_url

    def set_bg_image_props(self, image_url, min_percentage, max_percentage):
        self.image_url = image_url
        self.min_percentage = min_percentage if min_percentage >= 0 else 0
        self.max_percentage = max_percentage if max_percentage <= 100 else 100

    def set_font_props(self, font, font_color, font_size, align,
            x_offset_len, y_offset_len):
        if align not in ("center", "left", "right"):
            align = "center"
        self.align = align

        # use default font if it doesn't exist
        if not font or not os.path.exists(default_font_path + font):
            g.log.error("font %s doesn't exist" % (default_font_path + font))
            font = default_font
        self.font = font
        self.font_color = font_color
        self.font_size = font_size
        self.font_path = default_font_path

        # specifies the end of the text area (used for center align)
        self.offset_len = (int(x_offset_len), int(y_offset_len))


class DynamicCreative(object):
    def __init__(self, creative_id, percent):
        self.creative_id = creative_id
        self.percent = percent
        self.progress_bar = None
        self.font_prefs = None
        self.image_collection = []

        self.background_item = None
        self.background_image = None

        self.output_path = output_path
        self.output_name = "goldvertisement_" + str(creative_id) + ".png"
        self.output_location = self.output_path + self.output_name

    def set_background(self):
        '''choose the background image based on the current gold goal percentage'''
        for image in self.image_collection:
            if self.percent >= image.min_percentage:
                # if max_percentage doesn't exist or is 100, use for percent >= 100
                if (self.percent < image.max_percentage or
                    (getattr(image, 'max_percentage', 100) >= 100 and 
                        self.percent >= 100)):
                    self.background_item = image
                    break

        if not self.background_item:
            self.background_item = image
            g.log.error("Missing percentage range for creative %s" % self.creative_id)
        self.background_image = url_to_image(str(self.background_item.image_url))

    def build_creative(self):
        '''choose the background image based on the percentage, impose the progress_bar
        on top of it. add text on top if a font_prefs section exists.
        save the image to a file which can then be sent to adzerk
        '''
        self.set_background()
        progress_bar = url_to_image(self.progress_bar.image_url)
        self.draw_progress_bar(progress_bar, self.progress_bar.offset, self.percent/100.0)
        self.background_image.paste(progress_bar, self.background_item.offset, progress_bar)

        if self.font_prefs:
            self.draw_text(self.background_image)

        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        self.background_image.save(self.output_location)

    def draw_progress_bar(self, image, offset, percent):
        '''draw a rectangle on the progress_bar outside of the current gold goal %
        and fill it with white'''
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            [(offset[0]+(image.size[0]*percent), offset[1]),
                (offset[0]+image.size[0], offset[1]+image.size[1])],
            fill=(255, 255, 255))
        return image

    def draw_text(self, image):
        try:
            font = ImageFont.truetype(self.font_prefs.font,
                    int(self.font_prefs.font_size))
        except:
            font = ImageFont.load_default()

        text = "%d%%" % self.percent
        text_size = font.getsize(text)
        left_offset, top_offset = self.get_align_offsets(text_size)
        draw = ImageDraw.Draw(image)
        draw.text((left_offset, top_offset), text,
            font=font, fill=self.font_prefs.font_color)
        return image

    def get_align_offsets(self, text_size):
        '''if text_size > offset window, it will still be aligned left/center/right'''
        left_offset = self.font_prefs.offset[0]
        top_offset = self.font_prefs.offset[1]
        left_offset_len = self.font_prefs.offset_len[0]
        top_offset_len = self.font_prefs.offset_len[1]

        if self.font_prefs.align == 'center':
            left_offset = left_offset + (left_offset_len-text_size[0])/2
            top_offset = top_offset + (top_offset_len-text_size[1])/2
        elif self.font_prefs.align == 'right':
            left_offset = (left_offset_len-text_size[0]) - left_offset
            top_offset = (top_offset_len-text_size[1]) - top_offset
        return left_offset, top_offset


def update_gold_creatives(percent=None, font_path=None, output_path=None):
    sections = DynamicCreativeWiki.get_all()

    if not percent:
        gold_goal = GoldGoal()
        percent = gold_goal.percent_filled

    enabled_creatives = set()
    progress_bars = {}
    bg_images = defaultdict(list)
    font_prefs = {}

    for item in sections:
        creative_id = item.creative_id
        enabled_creatives.add(creative_id)

        item_type = item.item_type
        if item_type == 'progress_bar':
            progress_bars[creative_id] = item
        elif item_type == 'bg_image':
            bg_images[creative_id].append(item)
        elif item_type == 'font_prefs':
            if font_path:
                item.font_path = font_path
            font_prefs[creative_id] = item

    for creative_id in enabled_creatives:
        dc = DynamicCreative(creative_id, percent)
        if creative_id not in progress_bars or creative_id not in bg_images:
            g.log.error("Creative %s is missing an item" % creative_id)
            continue

        dc.font_prefs = font_prefs.get(creative_id, None)
        dc.progress_bar = progress_bars[creative_id]
        dc.image_collection = bg_images[creative_id]
        dc.build_creative()

        # upload the image file to adzerk
        image = {'image': open(dc.output_location, 'rb')}
        try:
            adzerk_api.Creative.upload(creative_id, image)
            g.log.debug("uploaded creative %s" % creative_id)
        except:
            g.log.error("Creative %s could not be uploaded" % creative_id)
