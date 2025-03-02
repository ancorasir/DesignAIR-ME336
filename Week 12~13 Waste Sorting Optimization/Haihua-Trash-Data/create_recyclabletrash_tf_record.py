# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
r"""Convert raw COCO dataset to TFRecord for object_detection.

Example usage:
python create_recyclabletrash_tf_record.py \
      --image_dir="/raid/wanfang/Documents/simple_recyclable" \
      --object_annotations_file="/raid/wanfang/Documents/simple_recyclable/train.json" \
      --output_file_prefix="/raid/wanfang/Documents/tfrecords/recyclable-trash-tfrecords" \
      --num_shards=4
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import hashlib
import io
import json
import logging
import multiprocessing
import os
from absl import app
from absl import flags
import numpy as np
import PIL.Image

from pycocotools import mask
from object_detection.utils import dataset_util
import tensorflow.compat.v1 as tf

flags.DEFINE_boolean(
    'include_masks', False, 'Whether to include instance segmentations masks '
    '(PNG encoded) in the result. default: False.')
flags.DEFINE_string('image_dir', '/raid/wanfang/Documents/simple_recyclable', 'Directory containing images.')
flags.DEFINE_string(
    'image_info_file', None, 'File containing image information. '
    'Tf Examples in the output files correspond to the image '
    'info entries in this file. If this file is not provided '
    'object_annotations_file is used if present. Otherwise, '
    'caption_annotations_file is used to get image info.')
flags.DEFINE_string(
    'object_annotations_file', '/raid/wanfang/Documents/simple_recyclable/train.json', 'File containing object '
    'annotations - boxes and instance masks.')
flags.DEFINE_string('caption_annotations_file', '', 'File containing image '
                    'captions.')
flags.DEFINE_string('output_file_prefix', '/raid/wanfang/Documents/tfrecords/recyclable-trash-tfrecords-start1', 'Path to output file')
flags.DEFINE_integer('num_shards', 5, 'Number of shards for output file.')

FLAGS = flags.FLAGS

logger = tf.get_logger()
logger.setLevel(logging.INFO)


def create_tf_example(image,
                      image_dir,
                      category_index=None,
                      include_masks=False):
  """Converts image and annotations to a tf.Example proto.
  Args:
    image: dict with keys: [u'license', u'file_name', u'coco_url', u'height',
      u'width', u'date_captured', u'flickr_url', u'id']
    image_dir: directory containing the image files.
    bbox_annotations:
      list of dicts with keys: [u'segmentation', u'area', u'iscrowd',
        u'image_id', u'bbox', u'category_id', u'id'] Notice that bounding box
        coordinates in the official COCO dataset are given as [x, y, width,
        height] tuples using absolute coordinates where x, y represent the
        top-left (0-indexed) corner.  This function converts to the format
        expected by the Tensorflow Object Detection API (which is which is
        [ymin, xmin, ymax, xmax] with coordinates normalized relative to image
        size).
    category_index: a dict containing COCO category information keyed by the
      'id' field of each category.  See the label_map_util.create_category_index
      function.
    include_masks: Whether to include instance segmentations masks
      (PNG encoded) in the result. default: False.
  Returns:
    example: The converted tf.Example
    num_annotations_skipped: Number of (invalid) annotations that were ignored.
  Raises:
    ValueError: if the image pointed to by data['filename'] is not a valid JPEG
  """
  image_height = image['height']
  image_width = image['width']
  filename = image['file_name']
  image_id = image['image_id']
  bbox_annotations = image["annotations"]
  full_path = os.path.join(image_dir, filename[30:])
  with tf.gfile.GFile(full_path, 'rb') as fid:
    encoded_jpg = fid.read()
  encoded_jpg_io = io.BytesIO(encoded_jpg)
  image = PIL.Image.open(encoded_jpg_io)
  key = hashlib.sha256(encoded_jpg).hexdigest()
  feature_dict = {
      'image/height':
          dataset_util.int64_feature(image_height),
      'image/width':
          dataset_util.int64_feature(image_width),
      'image/filename':
          dataset_util.bytes_feature(filename.encode('utf8')),
      'image/source_id':
          dataset_util.bytes_feature(str(image_id).encode('utf8')),
      'image/key/sha256':
          dataset_util.bytes_feature(key.encode('utf8')),
      'image/encoded':
          dataset_util.bytes_feature(encoded_jpg),
      'image/format':
          dataset_util.bytes_feature('jpeg'.encode('utf8')),
  }
  num_annotations_skipped = 0
  if bbox_annotations:
    xmin = []
    xmax = []
    ymin = []
    ymax = []
    is_crowd = []
    category_names = []
    category_ids = []
    area = []
    encoded_mask_png = []
    for object_annotations in bbox_annotations:
      (x, y, width, height) = tuple(object_annotations['bbox'])
      if width <= 0 or height <= 0:
        num_annotations_skipped += 1
        continue
      if x + width > image_width or y + height > image_height:
        num_annotations_skipped += 1
        continue
      xmin.append(float(x) / image_width)
      xmax.append(float(x + width) / image_width)
      ymin.append(float(y) / image_height)
      ymax.append(float(y + height) / image_height)
      is_crowd.append(object_annotations['iscrowd'])
      category_id = int(object_annotations['category_id'])+1
      category_ids.append(category_id)
      category_names.append(category_index[category_id-1].encode('utf8'))
      area.append(1)
    feature_dict.update({
        'image/object/bbox/xmin':
            dataset_util.float_list_feature(xmin),
        'image/object/bbox/xmax':
            dataset_util.float_list_feature(xmax),
        'image/object/bbox/ymin':
            dataset_util.float_list_feature(ymin),
        'image/object/bbox/ymax':
            dataset_util.float_list_feature(ymax),
        'image/object/class/text':
            dataset_util.bytes_list_feature(category_names),
        'image/object/class/label':
            dataset_util.int64_list_feature(category_ids),
        'image/object/is_crowd':
            dataset_util.int64_list_feature(is_crowd),
        'image/object/area':
            dataset_util.float_list_feature(area),
    })
  example = tf.train.Example(features=tf.train.Features(feature=feature_dict))
  return key, example, num_annotations_skipped

def _pool_create_tf_example(args):
  return create_tf_example(*args)


def _load_images_info(images_info_file):
  with tf.gfile.GFile(images_info_file, 'r') as fid:
    images = json.load(fid)
  return images

def _create_tf_record_from_coco_annotations(images_info_file,
                                            image_dir,
                                            output_path,
                                            num_shards,
                                            object_annotations_file=None,
                                            caption_annotations_file=None,
                                            include_masks=False):
  """Loads COCO annotation json files and converts to tf.Record format.

  Args:
    images_info_file: JSON file containing image info. The number of tf.Examples
      in the output tf Record files is exactly equal to the number of image info
      entries in this file. This can be any of train/val/test annotation json
      files Eg. 'image_info_test-dev2017.json',
      'instance_annotations_train2017.json',
      'caption_annotations_train2017.json', etc.
    image_dir: Directory containing the image files.
    output_path: Path to output tf.Record file.
    num_shards: Number of output files to create.
    object_annotations_file: JSON file containing bounding box annotations.
    caption_annotations_file: JSON file containing caption annotations.
    include_masks: Whether to include instance segmentations masks
      (PNG encoded) in the result. default: False.
  """

  logging.info('writing to output path: %s', output_path)
  writers = [
      tf.python_io.TFRecordWriter(
          output_path + '-%02d-of-%02d.tfrecord' % (i, num_shards))
      for i in range(num_shards)
  ]
  images = _load_images_info(images_info_file)

  img_to_obj_annotation = None
  img_to_caption_annotation = None
  category_index = {0:'glass', 1:'paper', 2:'metal', 3:'plastic'}

  pool = multiprocessing.Pool()
  total_num_annotations_skipped = 0
  for idx, (_, tf_example, num_annotations_skipped) in enumerate(
      pool.imap(_pool_create_tf_example,
                [(image, image_dir, category_index, include_masks) for image in images])):
    if idx % 100 == 0:
      logging.info('On image %d of %d', idx, len(images))

    total_num_annotations_skipped += num_annotations_skipped
    writers[idx % num_shards].write(tf_example.SerializeToString())

  pool.close()
  pool.join()

  for writer in writers:
    writer.close()

  logging.info('Finished writing, skipped %d annotations.',
               total_num_annotations_skipped)


def main(_):
  assert FLAGS.image_dir, '`image_dir` missing.'
  assert (FLAGS.image_info_file or FLAGS.object_annotations_file or
          FLAGS.caption_annotations_file), ('All annotation files are '
                                            'missing.')
  if FLAGS.image_info_file:
    images_info_file = FLAGS.image_info_file
  elif FLAGS.object_annotations_file:
    images_info_file = FLAGS.object_annotations_file
  else:
    images_info_file = FLAGS.caption_annotations_file

  directory = os.path.dirname(FLAGS.output_file_prefix)
  if not tf.gfile.IsDirectory(directory):
    tf.gfile.MakeDirs(directory)

  _create_tf_record_from_coco_annotations(images_info_file, FLAGS.image_dir,
                                          FLAGS.output_file_prefix,
                                          FLAGS.num_shards,
                                          FLAGS.object_annotations_file,
                                          FLAGS.include_masks)


if __name__ == '__main__':
  logger = tf.get_logger()
  logger.setLevel(logging.INFO)
  app.run(main)
