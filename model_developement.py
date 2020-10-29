""" Imported libraries """
import os
import tensorflow as tf
from tensorflow.keras import layers, models
import numpy as np
from math import ceil, floor
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
import itertools
from tqdm import tqdm
from datetime import datetime
import random
import logging

""" Imported files """
import parameters


class Standardise_Randomness:
    def set_seeds(self, seed=123):
        """ Set random seed """
        os.environ['PYTHONHASHSEED'] = str(seed)
        random.seed(seed)
        tf.random.set_seed(seed)
        np.random.seed(seed)

    def set_threads(self):
        tf.config.threading.set_inter_op_parallelism_threads(1)
        tf.config.threading.set_intra_op_parallelism_threads(1)


standardisation = Standardise_Randomness()
standardisation.set_seeds()
standardisation.set_threads()


class Model_Development:
    def __init__(
            self
            , input_data: np.ndarray
            , model_params:  object = parameters.CNN_params()
            , model_hp_params: object = parameters.CNN_hyper_params()
            , running_mode: str = "full"
    ):
        self.data = input_data
        """ CNN parameters """
        self.params = model_params
        """ CNN hyper parameters """
        self.hyper_params = model_hp_params
        """ Others """
        self.mode = running_mode
        if not (self.mode == "test" or self.mode == "full"):
            raise ValueError("Running mode is NOT valid. Please give \"test\" or \"full\"")
        self.all_models = ""  # set automatically below

    def all_combinations(
            self
    ) -> np.ndarray:
        """ Calculate all possible combinations based on the given hyper parameters"""
        combinations = np.array(list(itertools.product(
            self.hyper_params.filter_num1, self.hyper_params.filter_num2, self.hyper_params.num_of_dense
            , self.hyper_params.dense_len1, self.hyper_params.dense_len2
        )))
        if self.mode == "full":
            return combinations
        elif self.mode == "test":
            logging.warning("*** reduced number of combinations is used due to the test running mode ***")
            return combinations[:10]

    def GN_initializer(self, seed_val: int = 123):
        initialiser = tf.keras.initializers.GlorotNormal(seed=seed_val)
        return initialiser

    def model_builder(
            self, conv1_filter_num, conv2_filter_num, num_of_dense, dense1_length, dense2_length, init_method
            , filter_size: int = 5
    ):
        """ Build a model based on the given parameters """
        # tf.random.set_seed(123)

        model = models.Sequential()

        model.add(layers.Conv1D(filters=conv1_filter_num
                                , kernel_size=filter_size
                                , strides=1
                                , padding="same"
                                , use_bias=True
                                , input_shape=self.data.shape[1:]
                                , kernel_initializer=init_method
                                , bias_initializer=init_method))
        model.add(layers.PReLU(alpha_initializer=init_method))
        model.add(layers.MaxPool1D())

        model.add(layers.Conv1D(filters=conv2_filter_num
                                , kernel_size=floor(filter_size / 2)
                                , strides=1
                                , padding="same"
                                , use_bias=True
                                , kernel_initializer=init_method
                                , bias_initializer=init_method))
        model.add(layers.PReLU(alpha_initializer=init_method))
        model.add(layers.MaxPool1D())

        model.add(layers.Flatten())

        for i in range(num_of_dense):
            if i < 1:
                model.add(layers.Dense(units=dense1_length
                                       , use_bias=True
                                       , kernel_initializer=init_method
                                       , bias_initializer=init_method))
                model.add(layers.PReLU(alpha_initializer=init_method))
            else:
                model.add(layers.Dense(units=dense2_length
                                       , use_bias=True
                                       , kernel_initializer=init_method
                                       , bias_initializer=init_method))
                model.add(layers.PReLU(alpha_initializer=init_method))

        model.add(layers.Dense(units=1
                               , use_bias=True
                               , kernel_initializer=init_method
                               , bias_initializer=init_method))
        model.add(layers.PReLU(alpha_initializer=init_method))

        model.compile(optimizer=tf.optimizers.Adam(learning_rate=self.params.initial_learning_rate),
                      loss=tf.keras.losses.MeanAbsolutePercentageError(name="MAPE"),
                      metrics=[tf.keras.metrics.MeanAbsoluteError(name="MAE")
                               , tf.keras.metrics.RootMeanSquaredError(name="RMSE")])
        return model

    def build_all_models(self, initialisation):
        """ Build all models based on all possible combinations """
        combinations = self.all_combinations()
        models = list(map(lambda combin:
                          self.model_builder(conv1_filter_num=combin[0]
                                             , conv2_filter_num=combin[1]
                                             , num_of_dense=combin[2]
                                             , dense1_length=combin[3]
                                             , dense2_length=combin[4]
                                             , init_method=initialisation)
                          , tqdm(combinations)))
        self.all_models = models
        return self.all_models

    def partitions_split(
            self, partition_length: int = 60
    ) -> list:
        """ Brake all models in partitions """
        if len(self.all_models) <= partition_length:  # if number of models < partition length
            partitions = list(self.all_models)
            return partitions
        else:
            partitions = list(map(lambda x:
                                  self.all_models[x * partition_length:(x + 1) * partition_length],
                                  range(ceil(len(self.all_models) / partition_length))))
            return partitions

    def dict_partitions(
            self, partition_length: int = 60
    ) -> dict:
        """ Create dictionary of partitions """
        all_partitions = {}
        if len(self.all_models) <= partition_length:
            partition_dict = {f"models{partition_length}": self.partitions_split(partition_length)}
            return partition_dict
        else:
            for ind, partition in enumerate(
                    self.partitions_split(partition_length)
            ):
                part_dict = {f"models{(ind + 1) * partition_length}": partition}
                all_partitions.update(part_dict)
            return all_partitions

    def get_partition_number(self):
        get_num = list(map(lambda part:
                           int(part[1]),
                           list(map(lambda key:
                                    key.split("s"),
                                    self.dict_partitions()))))
        return get_num

    def reporting(
            self, model, results: dict
    ) -> pd.DataFrame:
        """ Generate a report for models, epochs and metrics """
        report = pd.DataFrame(columns=["models", "epochs"])
        report["epochs"] = np.arange(1, len(results["loss"]) + 1, 1)
        report["models"] = model
        for key in results:
            report[key] = results[key]
        return report

    def existence_check(
            self, item
    ) -> bool:
        """ Check whether the report exists in the current directory """
        file_name = item.replace("models", "report")
        return any(list(map(lambda file: file.startswith(file_name), os.listdir())))

    def auto_grid_cv(
            self, training_data: np.ndarray, targets: np.ndarray, callback_list: list
    ) -> None:
        """ Training process with Cross Validation by partition
            Automatic Execution - Check whether the corresponding report exists in the current directory
            If not -> training is executed for the corresponding partition """
        partitions = self.dict_partitions()
        partition_numb = self.get_partition_number()
        now = datetime.today().strftime("%Y%m%d_%H%M%S")
        numb_ind = -1
        report = pd.DataFrame()
        series_cv = list(TimeSeriesSplit(n_splits=self.params.folds).split(training_data))

        for part in partitions:
            numb_ind += 1
            if self.existence_check(part):
                print("Report already exists")
            else:
                print("New report")
                os.mkdir(f"saved_models{partition_numb[numb_ind]}_{now}")
                for ind, model in enumerate(tqdm(partitions[part])):
                    for i in range(len(series_cv)):
                        history = model.fit(x=training_data[:len(series_cv[i][0])]
                                            , y=targets[:len(series_cv[i][0])]
                                            , verbose=0
                                            , epochs=self.params.epochs
                                            , batch_size=self.params.batch_size
                                            , shuffle=False
                                            , validation_data=(training_data[:len(series_cv[i][1])]
                                                               , targets[:len(series_cv[i][1])])
                                            , callbacks=callback_list)
                    report = report.append(self.reporting(ind + partition_numb[numb_ind] - 60, history.history))
                    tf.keras.models.save_model(model=model, filepath=f"saved_models{partition_numb[numb_ind]}_{now}/"
                                                                     + f"model_{ind + partition_numb[numb_ind] - 60}.h5")
                report.to_csv(f"report{partition_numb[numb_ind]}_{now}.csv", index=False)

    def manual_grid_cv(
            self, partition, partition_num, training_data, targets, callback_list
    ):
        """ Training process with Cross Validation by partition
            Manual Execution - Run only the given partition
            partition: list(models) """
        tf.random.set_seed(123)
        now = datetime.today().strftime("%Y%m%d_%H%M%S")
        os.mkdir(f"saved_models{partition_num}_{now}")
        report = pd.DataFrame()
        series_cv = list(TimeSeriesSplit(n_splits=self.params.folds).split(training_data))

        for ind, model in enumerate(tqdm(partition)):
            for i in range(len(series_cv)):
                history = model.fit(x=training_data[:len(series_cv[i][0])]
                                    , y=targets[:len(series_cv[i][0])]
                                    , verbose=0
                                    , epochs=self.params.epochs
                                    , batch_size=self.params.batch_size
                                    , shuffle=False
                                    , validation_data=(training_data[:len(series_cv[i][1])]
                                                       , targets[:len(series_cv[i][1])])
                                    , callbacks=callback_list)
            report = report.append(self.reporting(ind + partition_num - 60, history.history))
            tf.keras.models.save_model(model=model, filepath=f"saved_models{partition_num}_{now}/"
                                                             + f"model_{ind + partition_num - 60}.h5")
        report.to_csv(f"report{partition_num}_{now}.csv", index=False)
        # mail_sender.send_email(dataframe=report, subject=str(partition_num))
