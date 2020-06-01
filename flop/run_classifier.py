# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
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
"""BERT finetuning runner."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
sys.path.append(sys.path[0] + '/../bert')

import collections
import os
import modeling
import modeling_flop
import optimization_flop
import tokenization
import tensorflow as tf
import numpy as np
import utils
from data_processor import *

flags = tf.flags

FLAGS = flags.FLAGS

## Required parameters
flags.DEFINE_string(
    "data_dir", None,
    "The input data dir. Should contain the .tsv files (or other data files) "
    "for the task.")

flags.DEFINE_string(
    "bert_config_file", None,
    "The config json file corresponding to the pre-trained BERT model. "
    "This specifies the model architecture.")

flags.DEFINE_string("task_name", None, "The name of the task to train.")

flags.DEFINE_string("vocab_file", None,
                    "The vocabulary file that the BERT model was trained on.")

flags.DEFINE_string(
    "output_dir", None,
    "The output directory where the model checkpoints will be written.")

## Other parameters

flags.DEFINE_string(
    "init_checkpoint", None,
    "Initial checkpoint (usually from a pre-trained BERT model).")

flags.DEFINE_bool(
    "do_lower_case", True,
    "Whether to lower case the input text. Should be True for uncased "
    "models and False for cased models.")

flags.DEFINE_integer(
    "max_seq_length", 128,
    "The maximum total input sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated, and sequences shorter "
    "than this will be padded.")

flags.DEFINE_bool("do_train", False, "Whether to run training.")

flags.DEFINE_bool("do_eval", False, "Whether to run eval on the dev set.")

flags.DEFINE_bool(
    "do_predict", False,
    "Whether to run the model in inference mode on the test set.")

flags.DEFINE_integer("train_batch_size", 32, "Total batch size for training.")

flags.DEFINE_integer("eval_batch_size", 8, "Total batch size for eval.")

flags.DEFINE_integer("predict_batch_size", 8, "Total batch size for predict.")

flags.DEFINE_float("learning_rate", 5e-5, "The initial learning rate for Adam.")

flags.DEFINE_float("num_train_epochs", 3.0,
                   "Total number of training epochs to perform.")

flags.DEFINE_float(
    "warmup_proportion", 0.1,
    "Proportion of training to perform linear learning rate warmup for. "
    "E.g., 0.1 = 10% of training.")

flags.DEFINE_integer("save_checkpoints_steps", 1000,
                     "How often to save the model checkpoint.")

flags.DEFINE_integer("iterations_per_loop", 1000,
                     "How many steps to make in each estimator call.")

tf.flags.DEFINE_string(
    "gcp_project", None,
    "[Optional] Project name for the Cloud TPU-enabled project. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

tf.flags.DEFINE_string("master", None, "[Optional] TensorFlow master URL.")

flags.DEFINE_string(
    "tensorbord_output_dir", None,
    "The tensorflow output dir.")

flags.DEFINE_integer(
    "learning_rate_warmup", 100,
    "The warmup steps of alpha and lambda.")
  
flags.DEFINE_float(
    "lambda_learning_rate", 1.0,
    "The initial learning rate of lambda.")

flags.DEFINE_float(
    "alpha_learning_rate", 0.01,
    "The initial learning rate of alpha.")

flags.DEFINE_float(
    "target_sparsity", 0.8,
    "The target sparsity of pruned model.")

flags.DEFINE_integer(
    "target_sparsity_warmup", 30000,
    "The warmup steps of target sparsity.")

flags.DEFINE_float(
    "attention_probs_dropout_prob", 0.1,
    "The dropout probability of attention layer.")

flags.DEFINE_float(
    "hidden_dropout_prob", 0.1,
    "The dropout probability of hidden layer.")

class InputFeatures(object):
  """A single set of features of data."""

  def __init__(self,
               input_ids,
               input_mask,
               segment_ids,
               label_id,
               is_real_example=True):
    self.input_ids = input_ids
    self.input_mask = input_mask
    self.segment_ids = segment_ids
    self.label_id = label_id
    self.is_real_example = is_real_example


def convert_single_example(ex_index, example, label_list, max_seq_length,
                           tokenizer):
  """Converts a single `InputExample` into a single `InputFeatures`."""
  sts = True if len(label_list) == 0 else False

  if not sts:
    label_map = {}
    for (i, label) in enumerate(label_list):
      label_map[label] = i

  tokens_a = tokenizer.tokenize(example.text_a)
  tokens_b = None
  if example.text_b:
    tokens_b = tokenizer.tokenize(example.text_b)

  if tokens_b:
    # Modifies `tokens_a` and `tokens_b` in place so that the total
    # length is less than the specified length.
    # Account for [CLS], [SEP], [SEP] with "- 3"
    _truncate_seq_pair(tokens_a, tokens_b, max_seq_length - 3)
  else:
    # Account for [CLS] and [SEP] with "- 2"
    if len(tokens_a) > max_seq_length - 2:
      tokens_a = tokens_a[0:(max_seq_length - 2)]

  # The convention in BERT is:
  # (a) For sequence pairs:
  #  tokens:   [CLS] is this jack ##son ##ville ? [SEP] no it is not . [SEP]
  #  type_ids: 0     0  0    0    0     0       0 0     1  1  1  1   1 1
  # (b) For single sequences:
  #  tokens:   [CLS] the dog is hairy . [SEP]
  #  type_ids: 0     0   0   0  0     0 0
  #
  # Where "type_ids" are used to indicate whether this is the first
  # sequence or the second sequence. The embedding vectors for `type=0` and
  # `type=1` were learned during pre-training and are added to the wordpiece
  # embedding vector (and position vector). This is not *strictly* necessary
  # since the [SEP] token unambiguously separates the sequences, but it makes
  # it easier for the model to learn the concept of sequences.
  #
  # For classification tasks, the first vector (corresponding to [CLS]) is
  # used as the "sentence vector". Note that this only makes sense because
  # the entire model is fine-tuned.
  tokens = []
  segment_ids = []
  tokens.append("[CLS]")
  segment_ids.append(0)
  for token in tokens_a:
    tokens.append(token)
    segment_ids.append(0)
  tokens.append("[SEP]")
  segment_ids.append(0)

  if tokens_b:
    for token in tokens_b:
      tokens.append(token)
      segment_ids.append(1)
    tokens.append("[SEP]")
    segment_ids.append(1)

  input_ids = tokenizer.convert_tokens_to_ids(tokens)

  # The mask has 1 for real tokens and 0 for padding tokens. Only real
  # tokens are attended to.
  input_mask = [1] * len(input_ids)

  # Zero-pad up to the sequence length.
  while len(input_ids) < max_seq_length:
    input_ids.append(0)
    input_mask.append(0)
    segment_ids.append(0)

  assert len(input_ids) == max_seq_length
  assert len(input_mask) == max_seq_length
  assert len(segment_ids) == max_seq_length

  label_id = label_map[example.label] if not sts else example.label

  feature = InputFeatures(
      input_ids=input_ids,
      input_mask=input_mask,
      segment_ids=segment_ids,
      label_id=label_id,
      is_real_example=True)
  return feature


def file_based_convert_examples_to_features(
    examples, label_list, max_seq_length, tokenizer, output_file):
  """Convert a set of `InputExample`s to a TFRecord file."""

  writer = tf.python_io.TFRecordWriter(output_file)

  for (ex_index, example) in enumerate(examples):
    if ex_index % 10000 == 0:
      tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

    feature = convert_single_example(ex_index, example, label_list,
                                     max_seq_length, tokenizer)

    def create_int_feature(values):
      f = tf.train.Feature(int64_list=tf.train.Int64List(value=list(values)))
      return f
    
    def create_float_feature(values):
      f = tf.train.Feature(float_list=tf.train.FloatList(value=list(values)))
      return f

    features = collections.OrderedDict()
    features["input_ids"] = create_int_feature(feature.input_ids)
    features["input_mask"] = create_int_feature(feature.input_mask)
    features["segment_ids"] = create_int_feature(feature.segment_ids)

    if len(label_list) == 0:
      features["label_ids"] = create_float_feature([feature.label_id])
    else:
      features["label_ids"] = create_int_feature([feature.label_id])

    features["is_real_example"] = create_int_feature(
        [int(feature.is_real_example)])

    tf_example = tf.train.Example(features=tf.train.Features(feature=features))
    writer.write(tf_example.SerializeToString())
  writer.close()


def file_based_input_fn_builder(input_file, seq_length, is_training,
                                drop_remainder, sts, batch_size):
  """Creates an `input_fn` closure to be passed to TrainSpec."""

  name_to_features = {
      "input_ids": tf.FixedLenFeature([seq_length], tf.int64),
      "input_mask": tf.FixedLenFeature([seq_length], tf.int64),
      "segment_ids": tf.FixedLenFeature([seq_length], tf.int64),
      "label_ids": tf.FixedLenFeature([], tf.int64) if not sts else tf.FixedLenFeature([], tf.float32),
      "is_real_example": tf.FixedLenFeature([], tf.int64),
  }

  def _decode_record(record, name_to_features):
    """Decodes a record to a TensorFlow example."""
    example = tf.parse_single_example(record, name_to_features)

    # tf.Example only supports tf.int64, but the TPU only supports tf.int32.
    # So cast all int64 to int32.
    for name in list(example.keys()):
      t = example[name]
      if t.dtype == tf.int64:
        t = tf.to_int32(t)
      example[name] = t

    return example

  def input_fn(params=None):
    """The actual input function."""
    # For training, we want a lot of parallel reading and shuffling.
    # For eval, we want no shuffling and parallel reading doesn't matter.
    d = tf.data.TFRecordDataset(input_file)
    if is_training:
      d = d.repeat()
      d = d.shuffle(buffer_size=100)

    d = d.apply(
        tf.contrib.data.map_and_batch(
            lambda record: _decode_record(record, name_to_features),
            batch_size=batch_size,
            drop_remainder=drop_remainder))

    return d

  return input_fn


def _truncate_seq_pair(tokens_a, tokens_b, max_length):
  """Truncates a sequence pair in place to the maximum length."""

  # This is a simple heuristic which will always truncate the longer sequence
  # one token at a time. This makes more sense than truncating an equal percent
  # of tokens from each, since if one sequence is very short then each token
  # that's truncated likely contains more information than a longer sequence.
  while True:
    total_length = len(tokens_a) + len(tokens_b)
    if total_length <= max_length:
      break
    if len(tokens_a) > len(tokens_b):
      tokens_a.pop()
    else:
      tokens_b.pop()


def create_model(bert_config, is_training, input_ids, input_mask, segment_ids,
                 labels, num_labels):
  """Creates a classification model."""
  model = modeling_flop.BertModelHardConcrete(
      config=bert_config,
      is_training=is_training,
      input_ids=input_ids,
      input_mask=input_mask,
      token_type_ids=segment_ids)

  # In the demo, we are doing a simple classification task on the entire
  # segment.
  #
  # If you want to use the token-level output, use model.get_sequence_output()
  # instead.
  sts = True if num_labels == 0 else False
  num_labels = max(num_labels, 1)

  output_layer = model.get_pooled_output()

  hidden_size = output_layer.shape[-1].value
  
  output_weights = tf.get_variable(
      "output_weights", [num_labels, hidden_size],
      initializer=tf.truncated_normal_initializer(stddev=0.02))

  output_bias = tf.get_variable(
      "output_bias", [num_labels], initializer=tf.zeros_initializer())

  with tf.variable_scope("loss"):
    if is_training:
      # I.e., 0.1 dropout
      output_layer = tf.nn.dropout(output_layer, keep_prob=0.9)

    logits = tf.matmul(output_layer, output_weights, transpose_b=True)
    logits = tf.nn.bias_add(logits, output_bias)

    if not sts:
      probabilities = tf.nn.softmax(logits, axis=-1)
      log_probs = tf.nn.log_softmax(logits, axis=-1)
      one_hot_labels = tf.one_hot(labels, depth=num_labels, dtype=tf.float32)
      per_example_loss = -tf.reduce_sum(one_hot_labels * log_probs, axis=-1)
    else:
      probabilities = None
      logits = tf.squeeze(logits, [-1])
      per_example_loss = tf.square(logits - labels)

    loss = tf.reduce_mean(per_example_loss)

    return (loss, per_example_loss, logits, probabilities)


def model_fn_builder(bert_config, num_labels, init_checkpoint, learning_rate,
                     num_train_steps, num_warmup_steps, 
                     learning_rate_warmup, lambda_learning_rate,
                     alpha_learning_rate, target_sparsity, target_sparsity_warmup):
  """Returns `model_fn` closure for Estimator."""

  def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
    """The `model_fn` for Estimator."""
    input_ids = features["input_ids"]
    input_mask = features["input_mask"]
    segment_ids = features["segment_ids"]
    label_ids = features["label_ids"]
    is_real_example = None
    if "is_real_example" in features:
      is_real_example = tf.cast(features["is_real_example"], dtype=tf.float32)
    else:
      is_real_example = tf.ones(tf.shape(label_ids), dtype=tf.float32)

    is_training = (mode == tf.estimator.ModeKeys.TRAIN)

    (total_loss, per_example_loss, logits, probabilities) = create_model(
        bert_config, is_training, input_ids, input_mask, segment_ids, label_ids,
        num_labels)

    sts = True if num_labels == 0 else False

    tvars = tf.trainable_variables()
    initialized_variable_names = {}
    if init_checkpoint:
      (assignment_map, initialized_variable_names
      ) = modeling.get_assignment_map_from_checkpoint(tvars, init_checkpoint)
      tf.train.init_from_checkpoint(init_checkpoint, assignment_map)

    tf.logging.info("**** Trainable Variables ****")
    for var in tvars:
      init_string = ""
      if var.name in initialized_variable_names:
        init_string = ", *INIT_FROM_CKPT*"
      tf.logging.info("  name = %s, shape = %s%s", var.name, var.shape,
                      init_string)

    output_spec = None
    if mode == tf.estimator.ModeKeys.TRAIN:

      train_op = optimization_flop.create_optimizer(
          total_loss,
          learning_rate,
          num_train_steps,
          num_warmup_steps,
          lr_warmup=learning_rate_warmup,
          lambda_lr=lambda_learning_rate,
          alpha_lr=alpha_learning_rate,
          target_sparsity=target_sparsity,
          target_sparsity_warmup=target_sparsity_warmup)
      
      if FLAGS.tensorbord_output_dir is not None:
        summary_hook = tf.train.SummarySaverHook(
          10,
          output_dir=FLAGS.tensorbord_output_dir,
          summary_op=tf.summary.merge_all())
        
        hyperparams = np.array(["batch_size=%d" % FLAGS.train_batch_size,
                                "epochs=%f" % FLAGS.num_train_epochs,
                                "warmup_proportion=%f" % FLAGS.warmup_proportion,
                                "init_lr=%f" % FLAGS.learning_rate,
                                "lambda_lr=%f" % FLAGS.lambda_learning_rate,
                                "alpha_lr=%f" % FLAGS.alpha_learning_rate,
                                "lr_warmup=%d" % FLAGS.learning_rate_warmup,
                                "target_sparsity=%f" % FLAGS.target_sparsity,
                                "target_sparsity_warmup=%d" % FLAGS.target_sparsity_warmup,
                                "hidden_dropout_prob=%f" % FLAGS.hidden_dropout_prob,
                                "attention_probs_dropout_prob=%f" % FLAGS.attention_probs_dropout_prob])
        hp_op = tf.summary.text("Hyperparameters", tf.constant(hyperparams))

        hyperparameters_hook = tf.train.SummarySaverHook(
          100000,
          output_dir=FLAGS.tensorbord_output_dir,
          summary_op=[hp_op])
         
        output_spec = tf.estimator.EstimatorSpec(
            mode=mode,
            loss=total_loss,
            train_op=train_op,
            training_hooks=[summary_hook, hyperparameters_hook])
      else:
        output_spec = tf.estimator.EstimatorSpec(
            mode=mode,
            loss=total_loss,
            train_op=train_op)
      
    elif mode == tf.estimator.ModeKeys.EVAL:

      # def metric_fn(per_example_loss, label_ids, logits, is_real_example):
      #   predictions = tf.argmax(logits, axis=-1, output_type=tf.int32)
      #   accuracy = tf.metrics.accuracy(
      #       labels=label_ids, predictions=predictions, weights=is_real_example)
      #   precision = tf.metrics.precision(
      #     labels=label_ids, predictions=predictions, weights=is_real_example)
      #   recall = tf.metrics.recall(
      #     labels=label_ids, predictions=predictions, weights=is_real_example)
      #   loss = tf.metrics.mean(values=per_example_loss, weights=is_real_example)
      #   tf.summary.scalar('accuracy', accuracy)
      #   return {
      #       "eval_accuracy": accuracy,
      #       "eval_loss": loss,
      #       "precision": precision,
      #       "recall": recall,
      #   }

      # def metric_fn_sts(per_example_loss, label_ids, logits, is_real_example):
      #   # Display labels and predictions	
        
        	
      #   # Compute Pearson correlation	
        
        	
      #   # Compute MSE	
      #   # mse = tf.metrics.mean(per_example_loss)    	
      #   mse = tf.metrics.mean_squared_error(label_ids, logits)	
        	

      # if sts:
      #   eval_metrics = (metric_fn_sts,
      #                 [per_example_loss, label_ids, logits, is_real_example])
      # else:
      #   eval_metrics = (metric_fn,
      #                 [per_example_loss, label_ids, logits, is_real_example])
      
      if not sts:
        predictions = tf.argmax(logits, axis=-1, output_type=tf.int32)
        accuracy = tf.metrics.accuracy(labels=label_ids, predictions=predictions)
        precision = tf.metrics.precision(labels=label_ids, predictions=predictions)
        recall = tf.metrics.recall(labels=label_ids, predictions=predictions)
        f1_score = (2 * precision[0] * recall[0]) / (precision[0] + recall[0])
        eval_metric_ops = {
            "eval_accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": (f1_score, tf.identity(f1_score))
          }
      else:
        concat1 = tf.contrib.metrics.streaming_concat(logits)
        concat2 = tf.contrib.metrics.streaming_concat(label_ids)
        pearson = tf.contrib.metrics.streaming_pearson_correlation(logits, label_ids)
        mse = tf.metrics.mean_squared_error(label_ids, logits)
        size = tf.size(logits)	
        indice_of_ranks_pred = tf.nn.top_k(logits, k=size)[1]	
        indice_of_ranks_label = tf.nn.top_k(label_ids, k=size)[1]	
        rank_pred = tf.nn.top_k(-indice_of_ranks_pred, k=size)[1]	
        rank_label = tf.nn.top_k(-indice_of_ranks_label, k=size)[1]	
        rank_pred = tf.to_float(rank_pred)	
        rank_label = tf.to_float(rank_label)	
        spearman = tf.contrib.metrics.streaming_pearson_correlation(rank_pred, rank_label)
        eval_metric_ops = {
            "pred": concat1,
            "label_ids": concat2,
            "pearson": pearson,
            "spearman": spearman,
            "MSE": mse
        }
      output_spec = tf.estimator.EstimatorSpec(
          mode=mode,
          loss=total_loss,
          eval_metric_ops=eval_metric_ops)
    else:
      if sts:
        output_spec = tf.estimator.EstimatorSpec(
          mode=mode,
          predictions={"logits": logits})      
      else:
        output_spec = tf.estimator.EstimatorSpec(
          mode=mode,
          predictions={"probabilities": probabilities})
    return output_spec

  return model_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def input_fn_builder(features, seq_length, is_training, drop_remainder):
  """Creates an `input_fn` closure to be passed to TPUEstimator."""

  all_input_ids = []
  all_input_mask = []
  all_segment_ids = []
  all_label_ids = []

  for feature in features:
    all_input_ids.append(feature.input_ids)
    all_input_mask.append(feature.input_mask)
    all_segment_ids.append(feature.segment_ids)
    all_label_ids.append(feature.label_id)

  def input_fn(params):
    """The actual input function."""
    batch_size = params["batch_size"]

    num_examples = len(features)

    # This is for demo purposes and does NOT scale to large data sets. We do
    # not use Dataset.from_generator() because that uses tf.py_func which is
    # not TPU compatible. The right way to load data is with TFRecordReader.
    d = tf.data.Dataset.from_tensor_slices({
        "input_ids":
            tf.constant(
                all_input_ids, shape=[num_examples, seq_length],
                dtype=tf.int32),
        "input_mask":
            tf.constant(
                all_input_mask,
                shape=[num_examples, seq_length],
                dtype=tf.int32),
        "segment_ids":
            tf.constant(
                all_segment_ids,
                shape=[num_examples, seq_length],
                dtype=tf.int32),
        "label_ids":
            tf.constant(all_label_ids, shape=[num_examples], dtype=tf.int32),
    })

    if is_training:
      d = d.repeat()
      d = d.shuffle(buffer_size=100)

    d = d.batch(batch_size=batch_size, drop_remainder=drop_remainder)
    return d

  return input_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def convert_examples_to_features(examples, label_list, max_seq_length,
                                 tokenizer):
  """Convert a set of `InputExample`s to a list of `InputFeatures`."""

  features = []
  for (ex_index, example) in enumerate(examples):
    if ex_index % 10000 == 0:
      tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

    feature = convert_single_example(ex_index, example, label_list,
                                     max_seq_length, tokenizer)

    features.append(feature)
  return features


def main(_):
  import time
  start = time.time()
  tf.logging.set_verbosity(tf.logging.INFO)

  time_str = utils.now_to_date()
  FLAGS.output_dir = os.path.join(FLAGS.output_dir, time_str)
  if FLAGS.tensorbord_output_dir is not None:
    FLAGS.tensorbord_output_dir = os.path.join(FLAGS.tensorbord_output_dir, time_str)

  processors = {
      "cola": ColaProcessor,
      "mnli": MnliProcessor,
      "mrpc": MrpcProcessor,
      "xnli": XnliProcessor,
      "mnli": MnliProcessor,
      "qnli": QnliProcessor,
      "qqp": QqpProcessor,
      "rte": RteProcessor,
      "wnli": WnliProcessor,
      "sst-2": Sst2Processor,
      "mrpc": MrpcProcessor,
      "sts-b": StsProcessor,
  }

  tokenization.validate_case_matches_checkpoint(FLAGS.do_lower_case,
                                                FLAGS.init_checkpoint)

  if not FLAGS.do_train and not FLAGS.do_eval and not FLAGS.do_predict:
    raise ValueError(
        "At least one of `do_train`, `do_eval` or `do_predict' must be True.")

  bert_config = modeling.BertConfig.from_json_file(FLAGS.bert_config_file)
  bert_config.attention_probs_dropout_prob = FLAGS.attention_probs_dropout_prob
  bert_config.hidden_dropout_prob = FLAGS.hidden_dropout_prob

  if FLAGS.max_seq_length > bert_config.max_position_embeddings:
    raise ValueError(
        "Cannot use sequence length %d because the BERT model "
        "was only trained up to sequence length %d" %
        (FLAGS.max_seq_length, bert_config.max_position_embeddings))

  tf.gfile.MakeDirs(FLAGS.output_dir)

  task_name = FLAGS.task_name.lower()

  if task_name not in processors:
    raise ValueError("Task not found: %s" % (task_name))

  processor = processors[task_name]()

  label_list = processor.get_labels()
  sts = True if len(label_list) == 0 else False

  tokenizer = tokenization.FullTokenizer(
      vocab_file=FLAGS.vocab_file, do_lower_case=FLAGS.do_lower_case)

  train_examples = None
  num_train_steps = None
  num_warmup_steps = None
  if FLAGS.do_train:
    train_examples = processor.get_train_examples(FLAGS.data_dir)
    num_train_steps = int(
        len(train_examples) / FLAGS.train_batch_size * FLAGS.num_train_epochs)
    num_warmup_steps = int(num_train_steps * FLAGS.warmup_proportion)

  model_fn = model_fn_builder(
      bert_config=bert_config,
      num_labels=len(label_list),
      init_checkpoint=FLAGS.init_checkpoint,
      learning_rate=FLAGS.learning_rate,
      num_train_steps=num_train_steps,
      num_warmup_steps=num_warmup_steps,
      learning_rate_warmup=FLAGS.learning_rate_warmup,
      lambda_learning_rate=FLAGS.lambda_learning_rate,
      alpha_learning_rate=FLAGS.alpha_learning_rate,
      target_sparsity=FLAGS.target_sparsity,
      target_sparsity_warmup=FLAGS.target_sparsity_warmup)

  run_config = tf.estimator.RunConfig(
    model_dir=FLAGS.output_dir,
    save_checkpoints_steps=FLAGS.save_checkpoints_steps)
  estimator = tf.estimator.Estimator(
    model_fn=model_fn,
    config=run_config)
  train_time = 0
  if FLAGS.do_train:
    train_file = os.path.join(FLAGS.output_dir, "train.tf_record")
    file_based_convert_examples_to_features(
        train_examples, label_list, FLAGS.max_seq_length, tokenizer, train_file)
    tf.logging.info("***** Running training *****")
    tf.logging.info("  Num examples = %d", len(train_examples))
    tf.logging.info("  Batch size = %d", FLAGS.train_batch_size)
    tf.logging.info("  Num steps = %d", num_train_steps)
    train_input_fn = file_based_input_fn_builder(
        input_file=train_file,
        seq_length=FLAGS.max_seq_length,
        is_training=True,
        drop_remainder=True,
        sts=sts,
        batch_size=FLAGS.train_batch_size)
    eval_examples = processor.get_dev_examples(FLAGS.data_dir)
    eval_file = os.path.join(FLAGS.output_dir, "eval.tf_record")
    file_based_convert_examples_to_features(
        eval_examples, label_list, FLAGS.max_seq_length, tokenizer, eval_file)
    eval_input_fn = file_based_input_fn_builder(
        input_file=eval_file,
        seq_length=FLAGS.max_seq_length,
        is_training=False,
        drop_remainder=False,
        sts=sts,
        batch_size=FLAGS.eval_batch_size)
    train_spec = tf.estimator.TrainSpec(
        input_fn=train_input_fn,
        max_steps=num_train_steps
    )
    eval_spec = tf.estimator.EvalSpec(
        input_fn=eval_input_fn,
        steps=None
    )
    tf.estimator.train_and_evaluate(
        estimator,
        train_spec,
        eval_spec)
    
    train_time = (time.time() - start) / 60
    start = time.time()
  
  if FLAGS.do_eval:
    eval_examples = processor.get_dev_examples(FLAGS.data_dir)
    num_actual_eval_examples = len(eval_examples)

    eval_file = os.path.join(FLAGS.output_dir, "eval.tf_record")
    file_based_convert_examples_to_features(
        eval_examples, label_list, FLAGS.max_seq_length, tokenizer, eval_file)

    tf.logging.info("***** Running evaluation *****")
    tf.logging.info("  Num examples = %d (%d actual, %d padding)",
                    len(eval_examples), num_actual_eval_examples,
                    len(eval_examples) - num_actual_eval_examples)
    tf.logging.info("  Batch size = %d", FLAGS.eval_batch_size)

    # This tells the estimator to run through the entire set.
    eval_steps = None

    eval_input_fn = file_based_input_fn_builder(
        input_file=eval_file,
        seq_length=FLAGS.max_seq_length,
        is_training=False,
        drop_remainder=False,
        sts=sts,
        batch_size=FLAGS.train_batch_size)

    result = estimator.evaluate(input_fn=eval_input_fn, steps=eval_steps)

    output_eval_file = os.path.join(FLAGS.output_dir, "eval_results.txt")
    with tf.gfile.GFile(output_eval_file, "w") as writer:
      tf.logging.info("***** Eval results *****")
      for key in sorted(result.keys()):
        if key == "precision" or key == "recall":
          continue
        tf.logging.info("  %s = %s", key, str(result[key]))
        writer.write("%s = %s\n" % (key, str(result[key])))
      eval_time = (time.time() - start) / 60
      writer.write("train_time: %fmin\n" % train_time)
      writer.write("eval_time: %fmin\n" % eval_time)
      tf.logging.info("train_time: %fmin\n" % train_time)
      tf.logging.info("eval_time: %fmin\n" % eval_time)

  if FLAGS.do_predict:
    predict_examples = processor.get_test_examples(FLAGS.data_dir)
    num_actual_predict_examples = len(predict_examples)

    predict_file = os.path.join(FLAGS.output_dir, "predict.tf_record")
    file_based_convert_examples_to_features(predict_examples, label_list,
                                            FLAGS.max_seq_length, tokenizer,
                                            predict_file)

    tf.logging.info("***** Running prediction*****")
    tf.logging.info("  Num examples = %d (%d actual, %d padding)",
                    len(predict_examples), num_actual_predict_examples,
                    len(predict_examples) - num_actual_predict_examples)
    tf.logging.info("  Batch size = %d", FLAGS.predict_batch_size)

    predict_input_fn = file_based_input_fn_builder(
        input_file=predict_file,
        seq_length=FLAGS.max_seq_length,
        is_training=False,
        drop_remainder=False,
        sts=sts,
        batch_size=FLAGS.train_batch_size)

    result = estimator.predict(input_fn=predict_input_fn)

    output_predict_file = os.path.join(FLAGS.output_dir, "test_results.tsv")
    with tf.gfile.GFile(output_predict_file, "w") as writer:
      num_written_lines = 0
      tf.logging.info("***** Predict results *****")
      if not sts:
        for (i, prediction) in enumerate(result):
          probabilities = prediction["probabilities"]
          if i >= num_actual_predict_examples:
            break
          output_line = str(i) + "\t".join(
              str(class_probability)
              for class_probability in probabilities) + "\n"
          writer.write(output_line)
          num_written_lines += 1
      else:
        for (i, prediction) in enumerate(result):
          logits = prediction["logits"]
          if i >= num_actual_predict_examples:
            break
          output_line = "%d\t%s" % (i, str(logits))
          writer.write(output_line)
          num_written_lines += 1
    assert num_written_lines == num_actual_predict_examples

if __name__ == "__main__":
  flags.mark_flag_as_required("data_dir")
  flags.mark_flag_as_required("task_name")
  flags.mark_flag_as_required("vocab_file")
  flags.mark_flag_as_required("bert_config_file")
  flags.mark_flag_as_required("output_dir")
  tf.app.run()
