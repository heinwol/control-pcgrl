import copy
import json
import os
import pickle
import shutil
import sys
import time
from functools import partial
from pathlib import Path
from pdb import set_trace as TT
from typing import Dict

import gymnasium as gym
import imageio
from tqdm import tqdm
import hydra
import matplotlib
import numpy as np
from hydra.core.config_store import ConfigStore
from omegaconf import DictConfig, OmegaConf
import ray
import torch as th
import wandb
from matplotlib import pyplot as plt
from ray import tune, air
from ray.rllib import MultiAgentEnv
from ray.rllib.algorithms import ppo

# from ray.rllib.algorithms.a3c import A2CTrainer
# from ray.rllib.algorithms.impala import ImpalaTrainer
from ray.rllib.models import ModelCatalog
from ray.rllib.policy.policy import PolicySpec
from ray.rllib.utils import check_env
from ray.tune import CLIReporter
from ray.air.integrations.wandb import (
    WandbLoggerCallback,
    # WandbTrainableMixin,
    # wandb_mixin,
)
from ray.tune.logger import DEFAULT_LOGGERS, pretty_print
from ray.tune.registry import register_env

from control_pcgrl.rl.callbacks import StatsCallbacks
from control_pcgrl.rl.envs import make_env
from control_pcgrl.rl.evaluate import evaluate
from control_pcgrl.rl.models import (
    NCA,
    ConvDeconv2d,  # noqa : F401
    CustomFeedForwardModel,
    CustomFeedForwardModel3D,
    Decoder,
    DenseNCA,
    SeqNCA,
    SeqNCA3D,
    WideModel3D,
    WideModel3DSkip,
)
from control_pcgrl.rl.utils import (
    IdxCounter,
    get_env_name,
    get_log_dir,
    get_map_width,
    TrainerConfigParsers,
    validate_config,
)
from control_pcgrl.rl.rllib_utils import ControllableTrainerFactory
from control_pcgrl.configs.config import Config, EvalConfig
import control_pcgrl
from control_pcgrl.envs.probs import PROBLEMS
from control_pcgrl.envs.probs.minecraft.minecraft_3D_holey_maze_prob import (
    Minecraft3DholeymazeProblem,
)
from control_pcgrl.task_assignment import set_map_fn
from rllib_inference import get_latest_ckpt

# Annoying, but needed since we can't go through `globals()` from inside hydra SLURM job. Is there a better way?
MODELS = {"NCA": NCA, "DenseNCA": DenseNCA, "SeqNCA": SeqNCA, "SeqNCA3D": SeqNCA3D}

matplotlib.use("Agg")

n_steps = 0
best_mean_reward, n_steps = -np.inf, 0


# TODO: Render this bloody scatter plot of control targets/vals!
# class CustomWandbLogger(WandbLogger):
#     def on_result(self, result: Dict):
#         res = super().on_result(result)
#         if 'custom_plots' in result:
#             for k, v in result['custom_plots'].items():
#                 wandb.log({k: v}, step=result['training_iteration'])


@hydra.main(version_base=None, config_path="../configs", config_name="train")
def main(cfg: Config) -> None:
    cfg = validate_config(cfg)
    if cfg is False:
        print("Invalid config!")
        return
    print("OmegaConf.to_yaml(cfg)")
    print(OmegaConf.to_yaml(cfg))
    print("Current working directory:", os.getcwd())

    # FIXME: Check for a 3D problem parent class.
    is_3D_env = False
    if "3D" in cfg.task.problem:
        is_3D_env = True

    log_dir = cfg.log_dir

    if not cfg.load and not cfg.overwrite:
        if os.path.isdir(log_dir):
            print(f"Log directory {log_dir} already exists. Will attempt to load.")

        else:
            os.makedirs(log_dir)
            print(f"Created new log directory {log_dir}")
    if cfg.overwrite:
        if not os.path.exists(log_dir):
            print(f"Log directory {log_dir} does not exist. Will create new directory.")
        else:
            # Overwrite the log directory.
            print(f"Overwriting log directory {log_dir}")
            shutil.rmtree(log_dir, ignore_errors=True)
        os.makedirs(log_dir, exist_ok=True)

    # Save the experiment settings for future reference.
    # with open(os.path.join(log_dir, 'settings.json'), 'w', encoding='utf-8') as f:
    #     json.dump(cfg.__dict__, f, ensure_ascii=False, indent=4)

    if not is_3D_env:
        if cfg.model.name is None:
            if cfg.representation == "wide":
                model_cls = ConvDeconv2d
            else:
                model_cls = CustomFeedForwardModel
        else:
            model_cls = MODELS[cfg.model.name]
    else:
        if cfg.representation == "wide3D":
            model_cls = MODELS[cfg.model.name] if cfg.model.name else WideModel3D
        else:
            model_cls = (
                MODELS[cfg.model.name] if cfg.model.name else CustomFeedForwardModel3D
            )

    ModelCatalog.register_custom_model("custom_model", model_cls)

    # If n_cpu is 0 or 1, we only use the local rllib worker. Specifying n_cpu > 1 results in use of remote workers.
    num_workers = 0 if cfg.hardware.n_cpu == 1 else cfg.hardware.n_cpu
    stats_callbacks = partial(StatsCallbacks, cfg=cfg)

    dummy_cfg = copy.copy(cfg)
    # dummy_cfg["render"] = False
    dummy_cfg.evaluation_env = False
    env = make_env(dummy_cfg)

    if issubclass(type(env), MultiAgentEnv):
        agent_obs_space = env.observation_space["agent_0"]
        agent_act_space = env.action_space["agent_0"]
    else:
        agent_obs_space = env.observation_space
        agent_act_space = env.action_space

    ### DEBUG ###
    if cfg.debug:
        from timeit import default_timer as timer

        n_eps = 100
        mean_ep_time = 0
        # Randomly step through 100 episodes
        for n_ep in tqdm(range(n_eps)):
            ep_start_time = timer()
            obs, info = env.reset()
            done = False
            n_step = 0
            while not done:
                # if i > 3:
                act = env.action_space.sample()
                # act = 0
                # else:
                # act = 0
                # Print shape of map
                obs, rew, done, truncated, info = env.step(act)

                # print(obs.transpose(2, 0, 1)[:, 10:-10, 10:-10])
                if cfg.render:
                    env.render()
                if isinstance(done, dict):
                    done = done["__all__"]
                n_step += 1

            ep_end_time = timer()
            ep_time = ep_end_time - ep_start_time

            print(f"Episode {n_ep} finished after {n_step} steps in {ep_time} seconds.")
            print(f"FPS: {n_step / ep_time}")

            mean_ep_time += ep_time

        mean_ep_time /= n_eps
        print(f"Average episode time: {mean_ep_time} seconds.")
        print(f"Average FPS: {n_step / mean_ep_time}.")

        # import pdb; pdb.set_trace()
        print("DEBUG: Congratulations! You can now use the environment.")
        sys.exit()

    # checkpoint_path_file = os.path.join(log_dir, 'checkpoint_path.txt')
    # FIXME: nope
    num_envs_per_worker = cfg.hardware.n_envs_per_worker if not cfg.infer else 1
    logger_type = (
        {"type": "ray.tune.logger.TBXLogger"} if not (cfg.infer or cfg.evaluate) else {}
    )
    eval_num_workers = num_workers if cfg.evaluate else 0
    model_cfg = {**cfg.model}

    # rllib will pass its own `name`
    model_cfg.pop("name")

    if cfg.multiagent.n_agents != 0:
        multiagent_config = {}
        if cfg.multiagent.policies == "centralized":
            multiagent_config["policies"] = {
                "default_policy": PolicySpec(
                    policy_class=None,
                    observation_space=agent_obs_space,
                    action_space=agent_act_space,
                    config=None,
                )
            }
            # multiagent_config['policy_mapping_fn'] = lambda agent_id: 'default_policy'
            multiagent_config["policy_mapping_fn"] = map_to_default_policy
        elif cfg.multiagent.policies == "decentralized":
            multiagent_config["policies"] = {
                f"agent_{i}": PolicySpec(
                    policy_class=None,
                    observation_space=agent_obs_space,
                    action_space=agent_act_space,
                    config={
                        "custom_model": "custom_model",
                        "custom_model_config": {
                            "dummy_env_obs_space": copy.copy(agent_obs_space),
                            **model_cfg,
                        },
                    },
                )
                for i in range(cfg.multiagent.n_agents)
            }
            # multiagent_config['policy_mapping_fn'] = lambda agent_id: agent_id
            multiagent_config["policy_mapping_fn"] = map_to_agent_id
        else:
            raise ValueError(
                "Unrecognized policy type. Policy values can either be centralized or decentralized"
            )

        multiagent_config["count_steps_by"] = "agent_steps"
        multiagent_config = {"multiagent": multiagent_config}

    else:
        multiagent_config = {}

    # The rllib trainer config (see the docs here: https://docs.ray.io/en/latest/rllib/rllib-training.html)
    num_workers = num_workers if not (cfg.evaluate or cfg.infer) else 1  #
    trainer_config = TrainerConfigParsers[cfg.algorithm](
        cfg,
        agent_obs_space,
        log_dir,
        logger_type,
        stats_callbacks,
        # checkpoint_path_file,
        model_cfg,
        multiagent_config,
        num_workers=num_workers,
        num_envs_per_worker=num_envs_per_worker,
        eval_num_workers=eval_num_workers,
    )

    register_env("pcgrl", make_env)

    # Log the trainer config, excluding overly verbose entries (i.e. Box observation space printouts).
    trainer_config_loggable = trainer_config.copy()
    # trainer_config_loggable.pop('observation_space')
    # trainer_config_loggable.pop('action_space')
    # trainer_config_loggable.pop('multiagent')
    print(
        f"Loading trainer with config: {pretty_print(trainer_config_loggable.to_dict())}"
    )

    trainer_name = "CustomTrainer"

    # Do inference, i.e., observe agent behavior for many episodes.
    if cfg.infer or cfg.evaluate:
        cfg: EvalConfig = cfg
        # trainer_config.update({
        # FIXME: The name of this config arg seems to have changed in rllib?
        # 'record_env': log_dir if cfg.record_env else None,
        # })
        if cfg.eval_random:
            print("WARNING: Evaluating random policy.")
            trainer = trainer_config.build()
        else:
            tuner = tune.Tuner.restore(os.path.join(log_dir, trainer_name))
            best_result = tuner.get_results().get_best_result(
                metric="episode_reward_mean", mode="max"
            )  # best_result.config["env_config"]["log_dir"] is still wrong
            ckpt = best_result.checkpoint
            if ckpt is None:
                ckpt = get_latest_ckpt(best_result.log_dir)

            trainer = trainer_config.build()
            trainer.restore(ckpt)

        if cfg.evaluate:
            eval_stats = evaluate(
                trainer,
                env,
                cfg,
                timesteps_total=best_result.metrics["timesteps_total"],
            )
            # sys.exit()
            ray.shutdown()
            return eval_stats, print("Yay!")

        elif cfg.infer:
            epi_index = 0

            def manual_infer():
                # Does not work for some reason? Rllib ignoring `trainer.config.evaluation_config['render_env']`
                # eval_stats = trainer.evaluate()
                # print(eval_stats)
                # For now we do it the old fashioned way.
                render_frames = []
                int_maps = []
                done = False
                obs, info = env.reset()
                render_frames.append(env.render())
                int_map = env.unwrapped._rep.unwrapped._map
                int_maps.append(int_map.tolist())
                while not done:
                    if cfg.multiagent.n_agents != 0:
                        action_dict = {}
                        for agent_id in range(cfg.multiagent.n_agents):
                            action_dict[
                                f"agent_{agent_id}"
                            ] = trainer.compute_single_action(obs[f"agent_{agent_id}"])
                        action = action_dict
                    else:
                        action = trainer.compute_single_action(obs)
                    obs, reward, done, truncated, info = env.step(action)
                    int_map = env.unwrapped._rep.unwrapped._map
                    int_maps.append(int_map.tolist())

                    if isinstance(done, dict):
                        done = done["__all__"]

                    render_frames.append(env.render())

                return render_frames, int_maps

            ep_names, ep_render_frames, ep_int_maps = [], [], []
            if cfg.vary_map_shapes:
                map_shapes = [(8, 8), (16, 16), (32, 32), (64, 64)]
                old_map_shape = cfg.task.map_shape
                for map_shape in map_shapes:
                    cfg.task.map_shape = map_shape
                    env.adjust_param(cfg=cfg)
                    for epi_index in range(cfg.infer_n_episodes):
                        render_frames, int_maps = manual_infer()
                        ep_render_frames.append(render_frames)
                        ep_int_maps.append(int_maps)
                        ep_name = (
                            f"map_shape_{map_shape[0]}x{map_shape[1]}_ep_{epi_index}"
                        )
                        ep_names.append(ep_name)
                        imageio.mimsave(
                            os.path.join(log_dir, f"{ep_name}.gif"),
                            render_frames,
                            duration=20,
                        )
                cfg.task.map_shape = old_map_shape
            # TODO: Eval different static tiles *and* map shapes.
            if cfg.static_prob is None:
                ep_names = [f"ep_{i}" for i in range(cfg.infer_n_episodes)]
                for epi_index in range(cfg.infer_n_episodes):
                    render_frames, int_maps = manual_infer()
                    ep_render_frames.append(render_frames)
                    ep_int_maps.append(int_maps)
            else:
                static_prob_vals = [0, 0.1, 0.3, 0.5, 0.7]
                static_wall_vals = [0, 3, 5, 7]
                # static_prob_vals = [0, 0.7]
                # static_wall_vals = [0]
                static_sweep = [
                    (static_prob, static_wall)
                    for static_prob in static_prob_vals
                    for static_wall in static_wall_vals
                ]
                # trainer.workers.foreach_env(lambda env: env.unwrapped._rep.set_eval_mode(True))
                env.unwrapped._rep.set_eval_mode(True)
                for static_prob, n_static_walls in static_sweep:
                    env.unwrapped._rep.set_static_prob(static_prob)
                    env.unwrapped._rep.set_n_static_walls(n_static_walls)
                    for epi_index in range(cfg.infer_n_episodes):
                        ep_names.append(
                            f"static_prob_{static_prob}_n_static_walls_{n_static_walls}_ep_{epi_index}"
                        )
                        render_frames, int_maps = manual_infer()
                        ep_render_frames.append(render_frames)
                        ep_int_maps.append(int_maps)

                    # eval_stats = {}

                    # Quite a slow hack. We need to rebuild the trainer to ensure the environment has the correct static tile
                    # parameters.
                    # trainer_cfg = trainer.config
                    # trainer_cfg.env_config['static_prob'] = static_prob
                    # trainer_cfg.env_config['n_static_walls'] = n_static_walls
                    # trainer = trainer_cfg.build()

                    # FIXME: We should be able to do something like this in theory. Why doesn't this work?
                    # trainer.workers.foreach_env(lambda env: env.unwrapped._rep.set_static_prob(static_prob))
                    # trainer.workers.foreach_env(lambda env: env.unwrapped._rep.set_n_static_walls(n_static_walls))
                    # trainer.workers.foreach_env(lambda env: env.reset())

                    print(
                        f"static probs: {trainer.workers.foreach_env(lambda env: env.unwrapped._rep.static_prob)}"
                    )
                    print(
                        f"static walls: {trainer.workers.foreach_env(lambda env: env.unwrapped._rep.n_static_walls)}"
                    )

            if cfg.render_mode == "save_gif":
                for ep_name, render_frames, int_maps in zip(
                    ep_names, ep_render_frames, ep_int_maps
                ):
                    # Save the rendered frames as a gif.
                    imageio.mimsave(
                        os.path.join(log_dir, f"{ep_name}.gif"),
                        render_frames,
                        duration=20,
                    )
                    # Save the list of integer maps as a json.
                    # with open(os.path.join(log_dir, f'int_maps_{epi_index}.json'), 'w') as f:
                    #     json.dump(int_maps, f)

        ray.shutdown()
        # Quit the program before agent starts training.
        return

    # tune.register_trainable("CustomPPO", PPOTrainer)
    tune.register_trainable(f"CustomTrainer", ControllableTrainerFactory(cfg.algorithm))

    # Limit the number of rows.
    reporter = CLIReporter(
        metric_columns={
            # "training_iteration": "itr",
            "timesteps_total": "timesteps",
            "custom_metrics/path-length_mean": "path-length",
            "custom_metrics/connected-path-length_mean": "cnct-path-length",
            "custom_metrics/regions_mean": "regions",
            "episode_reward_mean": "reward",
            "fps": "fps",
        },
        max_progress_rows=10,
    )
    # Add a custom metric column, in addition to the default metrics.
    # Note that this must be a metric that is returned in your training results.
    # reporter.add_metric_column("custom_metrics/path-length_mean")
    # reporter.add_metric_column("episode_reward_mean")

    ray.init()
    # loggers_dict = {'loggers': [WandbLoggerCallback]} if cfg.wandb else {}
    # loggers_dict = {'loggers': [CustomWandbLogger]} if cfg.wandb else {}
    callbacks_dict = (
        {
            "callbacks": [
                WandbLoggerCallback(
                    project="PCGRL_AIIDE_0",
                    # name=exp_name,
                    # id=exp_name,
                    name=log_dir,
                    id=log_dir,
                )
            ]
        }
        if cfg.wandb
        else {}
    )

    run_config = air.RunConfig(
        checkpoint_config=air.CheckpointConfig(
            checkpoint_at_end=True,
            checkpoint_frequency=cfg.checkpoint_freq,
            num_to_keep=3,
            checkpoint_score_attribute="episode_reward_mean",
            checkpoint_score_order="max",
        ),
        stop={"timesteps_total": cfg.timesteps_total},
        local_dir=cfg.log_dir,
        **callbacks_dict,
        verbose=1,
        progress_reporter=reporter,
    )

    tune_config = tune.TuneConfig(
        mode="max",
        metric="episode_reward_mean",
    )

    if not cfg.overwrite and os.path.exists(
        cfg.log_dir
    ):  # if loading from previous checkpoint
        # trainer = trainer_config.build()
        tuner = tune.Tuner.restore(os.path.join(str(log_dir), trainer_name))
        # Note that the `best_result` must always refer to the single experiment, as we are not sweeping over hyperparameters
        # with ray.tune.fit.
        start_new_run = False
        try:
            results = tuner.get_results()
        except RuntimeError:
            # Assume this is because we haven't trained/checkpointed at all. if no result in .pkl file
            start_new_run = True
        if not start_new_run:
            # Note that this `best_result` just points us to the single experiment (not loading earlier checkpoint here).
            best_result = results.get_best_result(
                metric="episode_reward_mean", mode="max"
            )
            steps_trained = best_result.metrics["timesteps_total"]
            if steps_trained >= cfg.timesteps_total:
                ray.shutdown()
                return print(
                    f"No need to reload, already trained {steps_trained} of {cfg.timesteps_total} steps."
                )

            if best_result.checkpoint is None:
                ckpt = get_latest_ckpt(log_dir=best_result.log_dir)
                if ckpt is None:  # If no checkpoint.
                    start_new_run = True
        if not start_new_run:
            # This is the latest checkpoint (not necessarily the best one).
            # ckpt = best_result.checkpoint
            # ckpt = best_result.best_checkpoints[0][0]
            def launch_run(resume):
                return tune.run(
                    run_or_experiment=trainer_name,
                    restore=ckpt,
                    config=trainer_config,
                    stop=run_config.stop,
                    checkpoint_at_end=run_config.checkpoint_config.checkpoint_at_end,
                    checkpoint_freq=run_config.checkpoint_config.checkpoint_frequency,
                    local_dir=run_config.local_dir,
                    verbose=1,
                    progress_reporter=reporter,
                    keep_checkpoints_num=run_config.checkpoint_config.num_to_keep,
                    resume=resume,
                )

            # Try to resume without creating extra unnecessary experiment folder.
            run_result = launch_run(resume=True)
            # If the experiment has not run to completion, try again but allow for a new experiment folder to be created.
            tuner = tune.Tuner.restore(os.path.join(str(log_dir), trainer_name))
            best_result = tuner.get_results().get_best_result(
                metric="episode_reward_mean", mode="max"
            )  # best_result.config["env_config"]["log_dir"] is still wrong
            steps_trained_new = best_result.metrics["timesteps_total"]
            if steps_trained_new == steps_trained:
                # NOTE: If we keyboard interrupt before more steps are trained on, we will end up here, because `tune.run`
                #   will exit gracefully.
                print(
                    "Experiment was not resumed successfully (because launched with `tuner.fit()`), restoring checkpoint without resuming, to create new experiment folder."
                )
                launch_run(resume=False)

                # tuner = tune.Tuner.restore(
                #     str(os.path.join(cfg.log_dir, trainer_name)),
                #     trainable=trainer_name,
                #     resume_errored=True,
                #     resume_unfinished=True,
                # )
                # tuner._local_tuner._run_config = run_config
    else:
        start_new_run = True
    if start_new_run:
        # Note that we could just use `tune.run` here, as above, since we are not sweeping over hyperparameters here.
        tuner = tune.Tuner(
            trainer_name,
            param_space=trainer_config,
            tune_config=tune_config,
            run_config=run_config,
        )

        try:
            analysis = tuner.fit()
            # TODO: Get stats from analysis and return for optuna in hydra ?
        except KeyboardInterrupt:
            ray.shutdown()

    ray.shutdown()
    return print("Yay! Experiment finished!")


def map_to_default_policy(agent_id, *args, **kwargs):
    return "default_policy"


def map_to_agent_id(agent_id, *args, **kwargs):
    return agent_id


if __name__ == "__main__":
    main()
