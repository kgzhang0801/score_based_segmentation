# -*- coding: utf-8 -*-

""" Deeplabv3+ model for tensorflow.keras.
This model is based on TF repo:
https://github.com/tensorflow/models/tree/master/research/deeplab
On Pascal VOC, original model gets to 84.56% mIOU

This model is only available for the TensorFlow backend,
due to its reliance on `SeparableConvolution` layers.

# Reference
- [Encoder-Decoder with Atrous Separable Convolution
    for Semantic Image Segmentation](https://arxiv.org/pdf/1802.02611.pdf)
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import warnings
import numpy as np
import tensorflow as tf

from tensorflow.keras.models import Model
from tensorflow.keras import layers
from tensorflow.keras.layers import Input
from tensorflow.keras.layers import Activation
from tensorflow.keras.layers import Dense
from tensorflow.keras.layers import Concatenate
from tensorflow.keras.layers import Softmax
from tensorflow.keras.layers import Dropout
from tensorflow.keras.layers import BatchNormalization
from tensorflow.keras.layers import Conv2D
from tensorflow.keras.layers import SeparableConv2D
from tensorflow.keras.layers import MaxPooling2D
from tensorflow.keras.layers import DepthwiseConv2D
from tensorflow.keras.layers import ZeroPadding2D
from tensorflow.keras.layers import GlobalAveragePooling2D
from tensorflow.keras.layers import GlobalMaxPooling2D
from tensorflow.keras.layers import AveragePooling2D
# from tensorflow.keras.engine import Layer # tf 1.x
from tensorflow.keras.layers import Layer
from tensorflow.keras.layers import InputSpec
# from tensorflow.keras.engine.topology import get_source_inputs # tf 1.x
from tensorflow.keras.utils import get_source_inputs
from tensorflow.keras import backend as K
from tensorflow.keras.applications import imagenet_utils
# from tensorflow.keras.utils import conv_utils # tf 1.x
# from tensorflow.keras.utils.data_utils import get_file # tf 1.x
from tensorflow.keras.utils import get_file

# TF_WEIGHTS_PATH = "https://github.com/bonlime/tensorflow.keras-deeplab-v3-plus/releases/download/1.0/deeplabv3_weights_tf_dim_ordering_tf_kernels.h5"
TF_WEIGHTS_PATH = "https://github.com/bonlime/keras-deeplab-v3-plus/releases/download/1.1/DeepLab3_xception_tf_dim_ordering_tf_kernels.h5"


# class BilinearUpsampling(Layer):
#     """Just a simple bilinear upsampling layer. Works only with TF.
#        Args:
#            upsampling: tuple of 2 numbers > 0. The upsampling ratio for h and w
#            output_size: used instead of upsampling arg if passed!
#     """

#     def __init__(self, upsampling=(2, 2), output_size=None, data_format=None, **kwargs):

#         super(BilinearUpsampling, self).__init__(**kwargs)

#         self.data_format = conv_utils.normalize_data_format(data_format)
#         self.input_spec = InputSpec(ndim=4)
#         if output_size:
#             self.output_size = conv_utils.normalize_tuple(
#                 output_size, 2, 'output_size')
#             self.upsampling = None
#         else:
#             self.output_size = None
#             self.upsampling = conv_utils.normalize_tuple(upsampling, 2, 'upsampling')

#     def compute_output_shape(self, input_shape):
#         if self.upsampling:
#             height = self.upsampling[0] * \
#                 input_shape[1] if input_shape[1] is not None else None
#             width = self.upsampling[1] * \
#                 input_shape[2] if input_shape[2] is not None else None
#         else:
#             height = self.output_size[0]
#             width = self.output_size[1]
#         return (input_shape[0],
#                 height,
#                 width,
#                 input_shape[3])

#     def call(self, inputs):
#         if self.upsampling:
#             return K.tf.image.resize_bilinear(inputs, (inputs.shape[1] * self.upsampling[0],
#                                                        inputs.shape[2] * self.upsampling[1]),
#                                               align_corners=True)
#         else:
#             return K.tf.image.resize_bilinear(inputs, (self.output_size[0],
#                                                        self.output_size[1]),
#                                               align_corners=True)

#     def get_config(self):
#         config = {'upsampling':self.upsampling,
#                   'output_size': self.output_size,
#                   'data_format': self.data_format}
#         base_config = super(BilinearUpsampling, self).get_config()
#         return dict(list(base_config.items()) + list(config.items()))


class BilinearUpsampling(Layer):
    """Just a simple bilinear upsampling layer. Works only with TF.
       Args:
           upsampling: tuple of 2 numbers > 0. The upsampling ratio for h and w
           output_size: used instead of upsampling arg if passed!
    """

    def __init__(self, upsampling=(2, 2), output_size=None, data_format=None, **kwargs):

        super(BilinearUpsampling, self).__init__(**kwargs)

        self.input_spec = InputSpec(ndim=4)
        if output_size:
            self.output_size = output_size
            self.upsampling = None
        else:
            self.output_size = None
            self.upsampling = upsampling

    def compute_output_shape(self, input_shape):
        if self.upsampling:
            height = self.upsampling[0] * \
                input_shape[1] if input_shape[1] is not None else None
            width = self.upsampling[1] * \
                input_shape[2] if input_shape[2] is not None else None
        else:
            height = self.output_size[0]
            width = self.output_size[1]
        return (input_shape[0],
                height,
                width,
                input_shape[3])

    def call(self, inputs):
        if self.upsampling:
            return tf.compat.v1.image.resize_bilinear(inputs, (inputs.shape[1] * self.upsampling[0],
                                                       inputs.shape[2] * self.upsampling[1]),
                                              align_corners=True)
        else:
            return tf.compat.v1.image.resize_bilinear(inputs, (self.output_size[0],
                                                       self.output_size[1]),
                                              align_corners=True)

    def get_config(self):
        config = {'upsampling':self.upsampling,
                  'output_size': self.output_size}
        base_config = super(BilinearUpsampling, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


def SepConv_BN(x, filters, prefix, stride=1, kernel_size=3, rate=1, depth_activation=False, epsilon=1e-3):
    """ SepConv with BN between depthwise & pointwise. Optionally add activation after BN
        Implements right "same" padding for even kernel sizes
        Args:
            x: input tensor
            filters: num of filters in pointwise convolution
            prefix: prefix before name
            stride: stride at depthwise conv
            kernel_size: kernel size for depthwise convolution
            rate: atrous rate for depthwise convolution
            depth_activation: flag to use activation between depthwise & poinwise convs
            epsilon: epsilon to use in BN layer
    """

    if stride == 1:
        depth_padding = 'same'
    else:
        kernel_size_effective = kernel_size + (kernel_size - 1) * (rate - 1)
        pad_total = kernel_size_effective - 1
        pad_beg = pad_total // 2
        pad_end = pad_total - pad_beg
        x = ZeroPadding2D((pad_beg, pad_end))(x)
        depth_padding = 'valid'

    if not depth_activation:
        x = Activation('relu')(x)
    x = DepthwiseConv2D((kernel_size, kernel_size), strides=(stride, stride), dilation_rate=(rate, rate),
                        padding=depth_padding, use_bias=False, name=prefix + '_depthwise')(x)
    x = BatchNormalization(name=prefix + '_depthwise_BN', epsilon=epsilon)(x)
    if depth_activation:
        x = Activation('relu')(x)
    x = Conv2D(filters, (1, 1), padding='same',
               use_bias=False, name=prefix + '_pointwise')(x)
    x = BatchNormalization(name=prefix + '_pointwise_BN', epsilon=epsilon)(x)
    if depth_activation:
        x = Activation('relu')(x)

    return x


def conv2d_same(x, filters, prefix, stride=1, kernel_size=3, rate=1):
    """Implements right 'same' padding for even kernel sizes
        Without this there is a 1 pixel drift when stride = 2
        Args:
            x: input tensor
            filters: num of filters in pointwise convolution
            prefix: prefix before name
            stride: stride at depthwise conv
            kernel_size: kernel size for depthwise convolution
            rate: atrous rate for depthwise convolution
    """
    if stride == 1:
        return Conv2D(filters,
                      (kernel_size, kernel_size),
                      strides=(stride, stride),
                      padding='same', use_bias=False,
                      dilation_rate=(rate, rate),
                      name=prefix)(x)
    else:
        kernel_size_effective = kernel_size + (kernel_size - 1) * (rate - 1)
        pad_total = kernel_size_effective - 1
        pad_beg = pad_total // 2
        pad_end = pad_total - pad_beg
        x = ZeroPadding2D((pad_beg, pad_end))(x)
        return Conv2D(filters,
                      (kernel_size, kernel_size),
                      strides=(stride, stride),
                      padding='valid', use_bias=False,
                      dilation_rate=(rate, rate),
                      name=prefix)(x)


def xception_block(inputs, depth_list, prefix, skip_connection_type, stride,
                   rate=1, depth_activation=False, return_skip=False):
    """ Basic building block of modified Xception network
        Args:
            inputs: input tensor
            depth_list: number of filters in each SepConv layer. len(depth_list) == 3
            prefix: prefix before name
            skip_connection_type: one of {'conv','sum','none'}
            stride: stride at last depthwise conv
            rate: atrous rate for depthwise convolution
            depth_activation: flag to use activation between depthwise & pointwise convs
            return_skip: flag to return additional tensor after 2 SepConvs for decoder
            """
    residual = inputs
    for i in range(3):
        residual = SepConv_BN(residual,
                              depth_list[i],
                              prefix + '_separable_conv{}'.format(i + 1),
                              stride=stride if i == 2 else 1,
                              rate=rate,
                              depth_activation=depth_activation)
        if i == 1:
            skip = residual
    if skip_connection_type == 'conv':
        shortcut = conv2d_same(inputs, depth_list[-1], prefix + '_shortcut',
                               kernel_size=1,
                               stride=stride)
        shortcut = BatchNormalization(name=prefix + '_shortcut_BN')(shortcut)
        outputs = layers.add([residual, shortcut])
    elif skip_connection_type == 'sum':
        outputs = layers.add([residual, inputs])
    elif skip_connection_type == 'none':
        outputs = residual
    if return_skip:
        return outputs, skip
    else:
        return outputs


def Deeplabv3(weights='pascal_voc', input_tensor=None, input_shape=(512, 512, 3), classes=21, OS=16, weights_path='', plot_model=False):
    """ Instantiates the Deeplabv3+ architecture

    Optionally loads weights pre-trained
    on PASCAL VOC. This model is available for TensorFlow only,
    and can only be used with inputs following the TensorFlow
    data format `(width, height, channels)`.
    # Arguments
        weights: one of 'pascal_voc' (pre-trained on pascal voc)
            or None (random initialization)
        input_tensor: optional tensorflow.keras tensor (i.e. output of `layers.Input()`)
            to use as image input for the model.
        input_shape: shape of input image. format HxWxC
            PASCAL VOC model was trained on (512,512,3) images
        classes: number of desired classes. If classes != 21,
            last layer is initialized randomly
        OS: determines input_shape/feature_extractor_output ratio. One of {8,16}
        plot_model: this is dummy parameter

    # Returns
        A tensorflow.keras model instance.

    # Raises
        RuntimeError: If attempting to run this model with a
            backend that does not support separable convolutions.
        ValueError: in case of invalid argument for `weights`

    """

    # if not (weights in {'pascal_voc', None}):
    #     raise ValueError('The `weights` argument should be either '
    #                      '`None` (random initialization) or `pascal_voc` '
    #                      '(pre-trained on PASCAL VOC)')

    # if K.backend() != 'tensorflow':
    #     raise RuntimeError('The Deeplabv3+ model is only available with '
    #                        'the TensorFlow backend.')

    if OS == 8:
        entry_block3_stride = 1
        middle_block_rate = 2  # ! Not mentioned in paper, but required
        exit_block_rates = (2, 4)
        atrous_rates = (12, 24, 36)
    else:
        entry_block3_stride = 2
        middle_block_rate = 1
        exit_block_rates = (1, 2)
        atrous_rates = (6, 12, 18)

    if input_tensor is None:
        img_input = Input(shape=input_shape)
    else:
        if not K.is_tensorflow.keras_tensor(input_tensor):
            img_input = Input(tensor=input_tensor, shape=input_shape)
        else:
            img_input = input_tensor

    x = Conv2D(32, (3, 3), strides=(2, 2),
               name='entry_flow_conv1_1', use_bias=False, padding='same')(img_input)
    x = BatchNormalization(name='entry_flow_conv1_1_BN')(x)
    x = Activation('relu')(x)

    x = conv2d_same(x, 64, 'entry_flow_conv1_2', kernel_size=3, stride=1)
    x = BatchNormalization(name='entry_flow_conv1_2_BN')(x)
    x = Activation('relu')(x)

    x = xception_block(x, [128, 128, 128], 'entry_flow_block1',
                       skip_connection_type='conv', stride=2,
                       depth_activation=False)
    x, skip1 = xception_block(x, [256, 256, 256], 'entry_flow_block2',
                              skip_connection_type='conv', stride=2,
                              depth_activation=False, return_skip=True)

    x = xception_block(x, [728, 728, 728], 'entry_flow_block3',
                       skip_connection_type='conv', stride=entry_block3_stride,
                       depth_activation=False)
    for i in range(16):
        x = xception_block(x, [728, 728, 728], 'middle_flow_unit_{}'.format(i + 1),
                           skip_connection_type='sum', stride=1, rate=middle_block_rate,
                           depth_activation=False)

    x = xception_block(x, [728, 1024, 1024], 'exit_flow_block1',
                       skip_connection_type='conv', stride=1, rate=exit_block_rates[0],
                       depth_activation=False)
    x = xception_block(x, [1536, 1536, 2048], 'exit_flow_block2',
                       skip_connection_type='none', stride=1, rate=exit_block_rates[1],
                       depth_activation=True)
    # end of feature extractor

    # branching for Atrous Spatial Pyramid Pooling
    # simple 1x1
    b0 = Conv2D(256, (1, 1), padding='same', use_bias=False, name='aspp0')(x)
    b0 = BatchNormalization(name='aspp0_BN', epsilon=1e-5)(b0)
    b0 = Activation('relu', name='aspp0_activation')(b0)

    # rate = 6 (12)
    b1 = SepConv_BN(x, 256, 'aspp1',
                    rate=atrous_rates[0], depth_activation=True, epsilon=1e-5)
    # rate = 12 (24)
    b2 = SepConv_BN(x, 256, 'aspp2',
                    rate=atrous_rates[1], depth_activation=True, epsilon=1e-5)
    # rate = 18 (36)
    b3 = SepConv_BN(x, 256, 'aspp3',
                    rate=atrous_rates[2], depth_activation=True, epsilon=1e-5)

    # Image Feature branch
    out_shape = int(np.ceil(input_shape[0] / OS))
    b4 = AveragePooling2D(pool_size=(out_shape, out_shape))(x)
    b4 = Conv2D(256, (1, 1), padding='same',
                use_bias=False, name='image_pooling')(b4)
    b4 = BatchNormalization(name='image_pooling_BN', epsilon=1e-5)(b4)
    b4 = Activation('relu')(b4)
    b4 = BilinearUpsampling(output_size=(out_shape, out_shape))(b4)

    # concatenate ASPP branches & project
    x = Concatenate()([b4, b0, b1, b2, b3])
    x = Conv2D(256, (1, 1), padding='same',
               use_bias=False, name='concat_projection')(x)
    x = BatchNormalization(name='concat_projection_BN', epsilon=1e-5)(x)
    x = Activation('relu')(x)
    x = Dropout(0.1)(x)

    # DeepLab v.3+ decoder

    # Feature projection
    # x4 (x2) block
    x = BilinearUpsampling(output_size=(int(np.ceil(input_shape[0] / 4)),
                                        int(np.ceil(input_shape[1] / 4))))(x)
    dec_skip1 = Conv2D(48, (1, 1), padding='same',
                       use_bias=False, name='feature_projection0')(skip1)
    dec_skip1 = BatchNormalization(
        name='feature_projection0_BN', epsilon=1e-5)(dec_skip1)
    dec_skip1 = Activation('relu')(dec_skip1)
    x = Concatenate()([x, dec_skip1])
    x = SepConv_BN(x, 256, 'decoder_conv0',
                   depth_activation=True, epsilon=1e-5)
    x = SepConv_BN(x, 256, 'decoder_conv1',
                   depth_activation=True, epsilon=1e-5)

    # you can use it with arbitary number of classes
    if classes == 21:
        last_layer_name = 'logits_semantic'
    else:
        last_layer_name = 'custom_logits_semantic'

    x = Conv2D(classes, (1, 1), padding='same', name=last_layer_name)(x)
    x = BilinearUpsampling(output_size=(input_shape[0], input_shape[1]))(x)

    # Ensure that the model takes into account
    # any potential predecessors of `input_tensor`.
    if input_tensor is not None:
        inputs = get_source_inputs(input_tensor)
    else:
        inputs = img_input

    model = Model(inputs, x, name='deeplabv3plus')

    # load weights

    if weights == 'pascal_voc':
        # weights_path = get_file('deeplabv3_weights_tf_dim_ordering_tf_kernels.h5',
        #                         TF_WEIGHTS_PATH,
        #                         cache_subdir='models')
        model.load_weights(weights_path, by_name=True, skip_mismatch=True)
    return model


class DeepLab3PlusOrigModel(Model):
    """ A wrapper for the Original DeepLab3+. """
    def __init__(self, keep_prob, num_classes, output_stride=16, input_shapes=(256, 256, 3), weights_name='pascal_voc', weights_path='', plot_model=False):
        super(DeepLab3PlusOrigModel, self).__init__(name='DeepLab3PlusOrigModel')

        self.weights_name = weights_name
        self.input_shapes=input_shapes
        self.num_classes=num_classes
        self.output_stride=output_stride
        self.weights_path=weights_path
        self.plot_model=plot_model

        self.model = Deeplabv3(weights=self.weights_name, input_tensor=None, input_shape=self.input_shapes, 
                               classes=self.num_classes, OS=self.output_stride, weights_path=self.weights_path, plot_model=self.plot_model)

    def call(self, inputs, training=False):
        outputs = self.model(inputs, training=training)
        if not training:
            outputs = tf.nn.softmax(outputs, axis=-1)
        return outputs

    def get_config(self):
        config = super(DeepLab3PlusOrigModel, self).get_config()
        config.update({'keep_prob': self.keep_prob,
                       'num_classes': self.num_classes,
                       'output_stride': self.output_stride})
        return config


def preprocess_input(x):
    """Preprocesses a numpy array encoding a batch of images.
    # Arguments
        x: a 4D numpy array consists of RGB values within [0, 255].
    # Returns
        Input array scaled to [-1.,1.]
    """
    return imagenet_utils.preprocess_input(x, mode='tf')
