# Copyright 2020, The TensorFlow Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Utility functions for membership inference attacks."""

import enum
import logging
from typing import Callable, Optional, Union

import numpy as np
from scipy import special


def log_loss(labels: np.ndarray,
             pred: np.ndarray,
             from_logits=False,
             small_value=1e-8) -> np.ndarray:
  """Computes the per-example cross entropy loss.

  Args:
    labels: numpy array of shape (num_samples,). labels[i] is the true label
      (scalar) of the i-th sample and is one of {0, 1, ..., num_classes-1}.
    pred: numpy array of shape (num_samples, num_classes) or (num_samples,). For
      categorical cross entropy loss, the shape should be (num_samples,
      num_classes) and pred[i] is the logits or probability vector of the i-th
      sample. For binary logistic loss, the shape should be (num_samples,) and
      pred[i] is the probability of the positive class.
    from_logits: whether `pred` is logits or probability vector.
    small_value: a scalar. np.log can become -inf if the probability is too
      close to 0, so the probability is clipped below by small_value.

  Returns:
    the cross-entropy loss of each sample
  """
  if labels.shape[0] != pred.shape[0]:
    raise ValueError('labels and pred should have the same number of examples,',
                     f'but got {labels.shape[0]} and {pred.shape[0]}.')
  classes = np.unique(labels)

  # Binary logistic loss
  if pred.size == pred.shape[0]:
    pred = pred.flatten()
    if classes.min() < 0 or classes.max() > 1:
      raise ValueError('Each value in pred is a scalar, so labels are expected',
                       f'to be {0, 1}. But got {classes}.')
    if from_logits:
      pred = special.expit(pred)

    indices_class0 = (labels == 0)
    prob_correct = np.copy(pred)
    prob_correct[indices_class0] = 1 - prob_correct[indices_class0]
    return -np.log(np.maximum(prob_correct, small_value))

  # Multi-class categorical cross entropy loss
  if classes.min() < 0 or classes.max() >= pred.shape[1]:
    raise ValueError('labels should be in the range [0, num_classes-1].')
  if from_logits:
    pred = special.softmax(pred, axis=-1)
  return -np.log(np.maximum(pred[range(labels.size), labels], small_value))


def squared_loss(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
  """Computes the per-example squared loss.

  Args:
    y_true: numpy array of shape (num_samples,) representing the true labels.
    y_pred: numpy array of shape (num_samples,) representing the predictions.

  Returns:
    the squared loss of each sample.
  """
  return (y_true - y_pred)**2


def multilabel_bce_loss(labels: np.ndarray,
                        pred: np.ndarray,
                        from_logits=False,
                        small_value=1e-8) -> np.ndarray:
  """Computes the per-multi-label-example cross entropy loss.

  Args:
    labels: numpy array of shape (num_samples, num_classes). labels[i] is the
      true multi-hot encoded label (vector) of the i-th sample and each element
      of the vector is one of {0, 1}.
    pred: numpy array of shape (num_samples, num_classes).  pred[i] is the
      logits or probability vector of the i-th sample.
    from_logits: whether `pred` is logits or probability vector.
    small_value: a scalar. np.log can become -inf if the probability is too
      close to 0, so the probability is clipped below by small_value.

  Returns:
    the cross-entropy loss of each sample for each class.
  """
  # Check arrays.
  if labels.shape[0] != pred.shape[0]:
    raise ValueError('labels and pred should have the same number of examples,',
                     f'but got {labels.shape[0]} and {pred.shape[0]}.')
  if not ((labels == 0) | (labels == 1)).all():
    raise ValueError(
        'labels should be in {0, 1}. For multi-label classification the labels '
        'should be multihot encoded.')
  # Check if labels vectors are multi-label.
  summed_labels = np.sum(labels, axis=1)
  if ((summed_labels == 0) | (summed_labels == 1)).all():
    logging.info(
        ('Labels are one-hot encoded single label. Every sample has at most one'
         ' positive label.'))
  if not from_logits and ((pred < 0.0) | (pred > 1.0)).any():
    raise ValueError(('Prediction probabilities are not in [0, 1] and '
                      '`from_logits` is set to False.'))

  # Multi-class multi-label binary cross entropy loss
  if from_logits:
    pred = special.expit(pred)
  bce = labels * np.log(pred + small_value)
  bce += (1 - labels) * np.log(1 - pred + small_value)
  return -bce


class LossFunction(enum.Enum):
  """An enum that defines loss function."""
  CROSS_ENTROPY = 'cross_entropy'
  SQUARED = 'squared'


def string_to_loss_function(string: str):
  """Convert string to the corresponding LossFunction."""

  if string == LossFunction.CROSS_ENTROPY.value:
    return LossFunction.CROSS_ENTROPY
  if string == LossFunction.SQUARED.value:
    return LossFunction.SQUARED
  raise ValueError(f'{string} is not a valid loss function name.')


def get_loss(loss: Optional[np.ndarray], labels: Optional[np.ndarray],
             logits: Optional[np.ndarray], probs: Optional[np.ndarray],
             loss_function: Union[Callable[[np.ndarray, np.ndarray],
                                           np.ndarray], LossFunction, str],
             loss_function_using_logits: Optional[bool],
             multilabel_data: Optional[bool]) -> Optional[np.ndarray]:
  """Calculates (if needed) losses.

  Args:
    loss: the loss of each example.
    labels: the scalar label of each example.
    logits: the logits vector of each example.
    probs: the probability vector of each example.
    loss_function: if `loss` is not available, `labels` and one of `logits`
      and `probs` are available, we will use this function to compute loss. It
      is supposed to take in (label, logits / probs) as input.
    loss_function_using_logits: if `loss_function` expects `logits` or
      `probs`.
    multilabel_data: if the data is from a multilabel classification problem.

  Returns:
    Loss (or None if neither the loss nor the labels are present).
  """
  if loss is not None:
    return loss
  if labels is None or (logits is None and probs is None):
    return None
  if loss_function_using_logits and logits is None:
    raise ValueError('We need logits to compute loss, but it is set to None.')
  if not loss_function_using_logits and probs is None:
    raise ValueError('We need probs to compute loss, but it is set to None.')

  predictions = logits if loss_function_using_logits else probs

  if isinstance(loss_function, str):
    loss_function = string_to_loss_function(loss_function)
  if loss_function == LossFunction.CROSS_ENTROPY:
    if multilabel_data:
      loss = multilabel_bce_loss(labels, predictions,
                                 loss_function_using_logits)
    else:
      loss = log_loss(labels, predictions, loss_function_using_logits)
  elif loss_function == LossFunction.SQUARED:
    loss = squared_loss(labels, predictions)
  else:
    loss = loss_function(labels, predictions)
  return loss
