# -*- coding:utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import os

import paddle.fluid as fluid
import paddlehub as hub
from paddlehub.common.paddle_helper import add_vars_prefix
from paddlehub.module.module import moduleinfo, serving

from emotion_detection_textcnn.net import textcnn_net
from emotion_detection_textcnn.processor import load_vocab, preprocess, postprocess


@moduleinfo(
    name="emotion_detection_textcnn",
    version="1.1.0",
    summary="Baidu's open-source Emotion Detection Model(TextCNN).",
    author="baidu-nlp",
    author_email="",
    type="nlp/sentiment_analysis")
class EmotionDetectionTextCNN(hub.NLPPredictionModule):
    def _initialize(self):
        """
        initialize with the necessary elements
        """
        self.pretrained_model_path = os.path.join(self.directory, "infer_model")
        self.vocab_path = os.path.join(self.directory, "assets", "vocab.txt")
        self.vocab = load_vocab(self.vocab_path)
        self._word_seg_module = None

        self.predict = self.emotion_classify

        self._set_config()

    @property
    def word_seg_module(self):
        """
        lac module
        """
        if not self._word_seg_module:
            self._word_seg_module = hub.Module(name="lac")
        return self._word_seg_module

    def context(self, trainable=False):
        """
        Get the input ,output and program of the pretrained emotion_detection_textcnn
        Args:
             trainable(bool): whether fine-tune the pretrained parameters of emotion_detection_textcnn or not
        Returns:
             inputs(dict): the input variables of emotion_detection_textcnn (words)
             outputs(dict): the output variables of emotion_detection_textcnn (the sentiment prediction results)
             main_program(Program): the main_program of lac with pretrained prameters
        """
        main_program = fluid.Program()
        startup_program = fluid.Program()
        with fluid.program_guard(main_program, startup_program):
            # word seq data
            data = fluid.layers.data(
                name="words", shape=[1], dtype="int64", lod_level=1)
            data_name = data.name

            pred, fc = textcnn_net(data, 240465)
            pred_name = pred.name
            fc_name = fc.name

            prefix_name = "@HUB_{}@".format(self.name)
            add_vars_prefix(program=main_program, prefix=prefix_name)

            for param in main_program.global_block().iter_parameters():
                param.trainable = trainable

            place = fluid.CPUPlace()
            exe = fluid.Executor(place)

            # load the emotion_detection_textcnn pretrained model
            def if_exist(var):
                return os.path.exists(
                    os.path.join(self.pretrained_model_path, var.name))

            fluid.io.load_vars(
                exe, self.pretrained_model_path, predicate=if_exist)

            inputs = {
                "words":
                main_program.global_block().vars[prefix_name + data_name]
            }
            outputs = {
                "class_probs":
                main_program.global_block().vars[prefix_name + pred_name],
                "sentence_feature":
                main_program.global_block().vars[prefix_name + fc_name]
            }

            return inputs, outputs, main_program

    @serving
    def emotion_classify(self, texts=[], data={}, use_gpu=False, batch_size=1):
        """
        Get the emotion prediction results results with the texts as input
        Args:
             texts(list): the input texts to be predicted, if texts not data
             data(dict): key must be 'text', value is the texts to be predicted, if data not texts
             use_gpu(bool): whether use gpu to predict or not
             batch_size(int): the program deals once with one batch
        Returns:
             results(list): the emotion prediction results
        """
        try:
            _places = os.environ["CUDA_VISIBLE_DEVICES"]
            int(_places[0])
        except:
            use_gpu = False

        if texts != [] and isinstance(texts, list) and data == {}:
            predicted_data = texts
        elif texts == [] and isinstance(data, dict) and isinstance(
                data.get('text', None), list) and data['text']:
            predicted_data = data["text"]
        else:
            raise ValueError(
                "The input data is inconsistent with expectations.")

        predicted_data = self.to_unicode(predicted_data)

        start_idx = 0
        iteration = int(math.ceil(len(predicted_data) / batch_size))
        results = []
        for i in range(iteration):
            if i < (iteration - 1):
                batch_data = predicted_data[start_idx:(start_idx + batch_size)]
            else:
                batch_data = predicted_data[start_idx:]
            start_idx = start_idx + batch_size
            processed_results = preprocess(self.word_seg_module, batch_data,
                                           self.vocab, use_gpu, batch_size)
            tensor_words = self.texts2tensor(processed_results)

            if use_gpu:
                batch_out = self.gpu_predictor.run([tensor_words])
            else:
                batch_out = self.cpu_predictor.run([tensor_words])
            batch_result = postprocess(batch_out[0], processed_results)
            results += batch_result
        return results

    def get_labels(self):
        """
        Get the labels which was used when pretraining
        Returns:
             self.labels(dict)
        """
        self.labels = {"positive": 2, "negative": 0, "neutral": 1}
        return self.labels


if __name__ == "__main__":
    emotion_detection_textcnn = EmotionDetectionTextCNN()
    # Data to be predicted
    test_text = ["今天天气真好", "湿纸巾是干垃圾", "别来吵我"]

    input_dict = {"text": test_text}
    results = emotion_detection_textcnn.emotion_classify(
        data=input_dict, batch_size=2)
    for result in results:
        print(result['text'])
        print(result['emotion_label'])
        print(result['emotion_key'])
        print(result['positive_probs'])
        print(result['negative_probs'])
        print(result['neutral_probs'])
