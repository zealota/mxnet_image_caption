# -*- conding=utf-8 -*-

"""
train module
"""
import mxnet as mx
import numpy as np
import json
import config
import logging
import time
import collections
from sym import vgg16_fc7, caption_module
from data_provider import caption_dataIter, init_cnn
from mxnet.model import save_checkpoint
import argparse
logging.basicConfig(level=logging.INFO)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epoches', default=20, type=int, help="epoches in training-stage", dest='epoches')
    parser.add_argument('--batch_size', default=50, type=int, help="batch_size in training-stage", dest='batch_size')
    parser.add_argument('--num_hidden', default=256, type=int, help="the number of hidden unit", dest='num_hidden')
    parser.add_argument('--lr', default=0.01, type=float, help="learning rate in training-stage", dest='lr')
    parser.add_argument('--freq_val', default=5, type=int, help="frequence of validation", dest='freq_val')
    parser.add_argument('--num_embed', default=256, type=int, help="the number of embedding dimension", dest='num_embed')
    parser.add_argument('--num_lstm_layer', default=256, type=int, help="the number of hidden_unit", dest='num_lstm_layer')
    parser.add_argument('--gpu', default=None, type=str, help="wether run on gpu device", dest='gpu')
    parser.add_argument('--prefix', default='./checkpoint/train', type=str, help="prefix of save checkpoint", dest='prefix')
    parser.add_argument('--period', default=5, type=int, help="times to save checkpoint in training-stage", dest='period')
    return parser.parse_args()


class callbacks:

    def __init__(self, nbatch, eval_metric, epoch):
        self.nbatch = nbatch
        self.eval_metric = eval_metric
        self.epoch = epoch


def main(args):
    learning_rate = args.lr
    epoches = args.epoches
    batch_size = args.batch_size
    num_hidden = args.num_hidden
    num_embed = args.num_embed
    num_lstm_layer = args.num_lstm_layer
    freq_val = args.freq_val
    val_flag = True if args.freq_val > 0 else False
    ctx = mx.cpu(0) if args.gpu is None else mx.gpu(int(args.gpu))
    prefix = args.prefix
    period = args.period

    with open(config.text_root, 'r') as f:
        captions = json.load(f)
    buckets = [10, 20, 30]
    # buckets = None
    train_data = caption_dataIter(
        captions=captions, batch_size=batch_size, mode='train')
    val_data = caption_dataIter(
        captions=captions, batch_size=batch_size, mode='val')

    ##########################################################################
    ########################### custom train process #########################
    ##########################################################################

    cnn_shapes = {
        'image_data': (batch_size, 3, 224, 224)
    }
    cnn_sym = vgg16_fc7('image_data')
    cnn_exec = cnn_sym.simple_bind(ctx=ctx, is_train=False, **cnn_shapes)
    lstm = caption_module(num_lstm_layer=num_lstm_layer, seq_len=train_data.sent_length+2,
                          vocab_size=train_data.vocab_size, num_hidden=num_hidden, num_embed=num_embed, batch_size=batch_size)
    lstm_shapes = {
        'image_feature': (batch_size, 4096),
        'word_data': (batch_size, train_data.sent_length+2),
        'softmax_label': (batch_size, train_data.sent_length+2)
    }

    lstm_exec = lstm.simple_bind(
        ctx=ctx, is_train=True, **lstm_shapes)

    # init params
    pretrain = mx.nd.load(config.vgg_pretrain)
    init_cnn(cnn_exec, pretrain)

    # init optimazer
    optimazer = mx.optimizer.create('adam')
    optimazer.lr = learning_rate
    updater = mx.optimizer.get_updater(optimazer)

    # init metric
    perplexity = mx.metric.Perplexity(ignore_label=-1)
    perplexity.reset()

    # callback
    params = callbacks(nbatch=0, eval_metric=perplexity, epoch=0)
    speedometer = mx.callback.Speedometer(batch_size=batch_size, frequent=20)
    for epoch in range(epoches):
        for i, batch in enumerate(train_data):

            # cnn forward, get image_feature
            cnn_exec.arg_dict['image_data'] = batch.data[0]
            cnn_exec.forward()
            image_feature = cnn_exec.outputs[0]

            # lstm forward
            lstm_exec.arg_dict['image_feature'] = image_feature
            lstm_exec.arg_dict['word_data'] = batch.data[1]
            lstm_exec.arg_dict['softmax_label'] = batch.label

            lstm_exec.forward(is_train=True)
            print batch.label
            params.eval_metric.update(labels=batch.label,
                                      preds=lstm_exec.outputs)
            lstm_exec.backward()
            params.epoch = epoch
            params.nbatch += 1
            speedometer(params)
            for j, name in enumerate(lstm.list_arguments()):
                if name not in lstm_shapes.keys():
                    updater(j, lstm_exec.grad_dict[
                            name], lstm_exec.arg_dict[name])
        train_data.reset()
        params.nbatch = 0

        if val_flag and epoch % freq_val == 0:
            for i, batch in enumerate(val_data):

                # cnn forward, get image_feature
                cnn_exec.arg_dict['image_data'] = batch.data[0]
                cnn_exec.forward()
                image_feature = cnn_exec.outputs[0]

                # lstm forward
                lstm_exec.arg_dict['image_feature'] = image_feature
                lstm_exec.arg_dict['word_data'] = batch.data[1]
                lstm_exec.arg_dict['softmax_label'] = batch.label

                lstm_exec.forward(is_train=False)
                params.eval_metric.update(labels=batch.label,
                                          preds=lstm_exec.outputs)
                params.epoch = epoch
                params.nbatch += 1
                speedometer(params)
            params.nbatch = 0
            val_data.reset()
        if period:
            save_checkpoint(prefix=prefix, epoch=epoch, symbol=lstm,
                            arg_params=lstm_exec.arg_dict,
                            aux_params=lstm_exec.aux_dict)
if __name__ == '__main__':
    args = parse_args()
    main(args)
