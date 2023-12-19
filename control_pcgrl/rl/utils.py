"""
Helper functions for train, infer, and eval modules.
"""
from pathlib import Path
from pdb import set_trace as TT
import copy
import glob
import os
import ray
import re

import numpy as np
import gymnasium as gym
from ray.rllib.algorithms.ppo import PPOConfig
from ray.tune import register_env
from gymnasium.spaces import Tuple

# from stable_baselines import PPO2
# from stable_baselines.bench import Monitor
# from stable_baselines.common.vec_env import DummyVecEnv, SubprocVecEnv
import torch

from control_pcgrl.configs.config import Config, EvalConfig
from control_pcgrl import wrappers
from control_pcgrl.task_assignment import set_map_fn
from control_pcgrl.rl.envs import make_env

PROJ_DIR = Path(__file__).parent.parent.parent

# NOTE: minecraft has to precede zelda since minecraft zelda maze has both phrases in its name.
MAP_WIDTHS = [
    ("binary", 16),
    ("minecraft_3D_rain", 7),
    ("minecraft_3D", 15),
    ("zelda", 16),
    ("sokoban", 5),
]

PROB_CONTROLS = {
    "binary_ctrl": [
        ["regions"],
        ["path-length"],
        ["regions", "path-length"],
        # ['emptiness', 'path-length'],
        # ["symmetry", "path-length"]
    ],
    "zelda_ctrl": [
        ["nearest-enemy"],
        ["path-length"],
        ["nearest-enemy", "path-length"],
        # ["emptiness", "path-length"],
        # ["symmetry", "path-length"],
    ],
    "sokoban_ctrl": [
        # ["crate"],
        ["sol-length"],
        ["crate", "sol-length"],
        # ["emptiness", "sol-length"],
        # ["symmetry", "sol-length"],
    ],
    "smb_ctrl": [
        ["enemies", "jumps"],
        # ["emptiness", "jumps"],
        # ["symmetry", "jumps"],
    ],
    "RCT": [
        # ['income'],
    ],
}


@ray.remote
class IdxCounter:
    """When using rllib trainer to train and simulate on evolved maps, this global object will be
    responsible for providing unique indices to parallel environments."""

    def __init__(self):
        self.count = 0
        self.keys = None

    def get(self, hsh):
        world_key_queue = self.hashes_to_keys[hsh]

        if not world_key_queue:
            raise Exception("No world keys provided.")

        return world_key_queue

    def set(self, i):
        # For inference
        self.count = i

    def set_keys(self, keys):
        self.count = 0
        self.keys = keys

    def set_hashes(self, hashes):
        """
        Note that we may assign multiple worlds to a single environment, or a single world to multiple environments.

        We will only assign a single world to multiple environments if duplicate keys were provided to `set_idxs()`.

        Args:
            hashes: A list of hashes, one per environment object.
        """
        hashes_to_keys = {h: [] for h in hashes}

        for i, wk in enumerate(self.keys):
            h = hashes[i % len(hashes)]
            hashes_to_keys[h].append(wk)

        self.hashes_to_keys = hashes_to_keys

    def scratch(self):
        return self.hashes_to_keys


def get_map_width(game):
    for k, v in MAP_WIDTHS:
        if k in game:
            return v
    raise Exception("Unknown game")


# def get_crop_size(game):
#     if "binary" in game:
#         return 32
#     elif "minecraft_3D" in game:
#         return 14
#     elif "zelda" in game:
#         return 32
#     elif "sokoban" in game:
#         return 10
#     else:
#         raise Exception("Unknown game")


# class RenderMonitor(Monitor):
#    """
#    Wrapper for the environment to save data in .csv files.
#    """
#
#    def __init__(self, env, rank, log_dir, **kwargs):
#        self.log_dir = log_dir
#        self.rank = rank
#        global_render = kwargs.get("render", False)
#        render_rank = kwargs.get("render_rank", 0)
#        self.render_me = False
#        if global_render and self.rank == render_rank:
#            self.render_me = True
#
#        if log_dir is not None:
#            log_dir = os.path.join(log_dir, str(rank))
#        Monitor.__init__(self, env, log_dir)
#
#    def step(self, action):
#        if self.render_me:
#            self.render()
#        ret = Monitor.step(self, action)
#
#        return ret


def get_action(obs, env, model, action_type=True):
    action = None

    if action_type == 0:
        action, _ = model.predict(obs)
    elif action_type == 1:
        action_prob = model.action_probability(obs)[0]
        action = np.random.choice(
            a=list(range(len(action_prob))), size=1, p=action_prob
        )
    else:
        action = np.array([env.action_space.sample()])

    return action


# def make_env(env_name, representation, rank=0, log_dir=None, **kwargs):
#    """
#    Return a function that will initialize the environment when called.
#    """
#    max_step = kwargs.get("max_step", None)
#    render = kwargs.get("render", False)
#
#    def _thunk():
#        if representation == "wide":
#            env = wrappers.ActionMapImagePCGRLWrapper(env_name, **kwargs)
#        else:
#            crop_size = kwargs.get("crop_size", 28)
#            env = wrappers.CroppedImagePCGRLWrapper(env_name, crop_size, **kwargs)
#
#        if max_step is not None:
#            env = wrappers.MaxStep(env, max_step)
#
#        if log_dir is not None and kwargs.get("add_bootstrap", False):
#            env = wrappers.EliteBootStrapping(
#                env, os.path.join(log_dir, "bootstrap{}/".format(rank))
#            )
#        # RenderMonitor must come last
#
#        if render or log_dir is not None and len(log_dir) > 0:
#            env = RenderMonitor(env, rank, log_dir, **kwargs)
#
#        return env
#
#    return _thunk


# def make_vec_envs(env_name, representation, log_dir, n_cpu, **kwargs):
#    """
#    Prepare a vectorized environment using a list of 'make_env' functions.
#    """
#    n_cpu = kwargs.pop("n_cpu", 1)
#
#    if n_cpu > 1:
#        env_lst = []
#
#        for i in range(n_cpu):
#            env_lst.append(make_env(env_name, representation, i, log_dir, **kwargs))
#        env = SubprocVecEnv(env_lst)
#    else:
#        env = DummyVecEnv([make_env(env_name, representation, 0, log_dir, **kwargs)])
#
#    return env


def get_env_name(game, representation):
    if "RCT" in game or "Micropolis" in game:
        env_name = "{}-v0".format(game)
    else:
        env_name = "{}-{}-v0".format(game, representation)

    return env_name


def get_log_dir(cfg: Config):
    default_dir = os.path.join(PROJ_DIR, "rl_runs")

    log_dir = os.path.join(
        cfg.runs_dir if cfg.runs_dir is not None else default_dir,
        cfg.algorithm,
        cfg.task.name,
        # "weights_" + "-".join(f"{k}-{v}" for k, v in cfg.task.weights.items()),
        cfg.representation,
        cfg.multiagent.policies,  # default to single policy
    )
    log_dir += "/"

    if cfg.model.name is not None:
        log_dir += cfg.model.name + "_"

    if cfg.controls is not None:
        log_dir += "" + "-".join(["ctrl"] + cfg.controls + "_")

    if cfg.change_percentage is not None:
        log_dir += "chng-{}_".format(cfg.change_percentage)

    if cfg.max_board_scans != 1:
        log_dir += "{}-scans_".format(cfg.max_board_scans)

    # Add obs_window shape
    if cfg.task.obs_window is not None:
        if len(cfg.task.obs_window) == 2:
            log_dir += "obsWin-{}x{}-".format(*cfg.task.obs_window)
        else:
            log_dir += "obsWin-{}x{}x{}-".format(*cfg.task.obs_window)

    if cfg.act_window is not None:
        log_dir += "actWin-{}x{}-".format(*cfg.act_window)

    if hasattr(cfg, "midep_trgs") and cfg.midep_trgs:
        log_dir += "midEpTrgs_"

    if hasattr(cfg, "alp_gmm") and cfg.alp_gmm:
        log_dir += "ALPGMM_"

    if cfg.multiagent.n_agents != 0:
        log_dir += f"{cfg.multiagent['n_agents']}-player_" + (
            "Show" if cfg.show_agents else ""
        )

    # TODO: Can have subdirectories for given settings of a given model type.
    if cfg.model.name is not None:
        log_dir += (
            f"{cfg.model.conv_filters}-convSz_" if cfg.model.conv_filters != 64 else ""
        )
        log_dir += (
            f"{cfg.model.fc_size}-fcSz_"
            if cfg.model.fc_size != 64 and cfg.model.name != "NCA"
            else ""
        )

    if cfg.model.name == "SeqNCA":
        log_dir += f"pw-{cfg.model.patch_width}_"

    if cfg.n_aux_tiles > 0:
        log_dir += f"{cfg.n_aux_tiles}-aux_"

    if cfg.static_prob is not None:
        log_dir += f"{cfg.static_prob}-static_"

    if cfg.n_static_walls is not None:
        log_dir += f"{cfg.n_static_walls}-staticWalls_"

    if cfg.learning_rate:
        log_dir += f"lr-{cfg.learning_rate:.1e}_"

    # Can't control `n_frame`, but if we did, wouldn't want to have this in experiment name in case we watned to extent
    # training later.
    # if cfg.n_frame is not None:
    #     exp_name += f"_nframe-{cfg.n_frame}"

    log_dir += f"{cfg.exp_id}"

    return log_dir


def validate_config(cfg: Config):
    """Set up the experiment name, and raise errors if the config has invalid combinations of hyperparameters (TODO).

    NOTE: This function `validate_config(validate_config(cfg)) == validate_config(cfg) ...`
    """

    cfg.static_tile_wrapper = (
        cfg.static_prob is not None or cfg.n_static_walls is not None
    )

    if cfg.task.obs_window is None:
        # This guy gotta observe the holes.
        if "holey" in cfg.task.problem:
            obs_window = cfg.task.map_shape * 2 + 2
        else:
            obs_window = cfg.task.map_shape * 2
        cfg.task.obs_window = obs_window

    cfg.env_name = get_env_name(cfg.task.problem, cfg.representation)
    # print('env name: ', cfg.env_name)
    cfg.log_dir = get_log_dir(cfg)

    if cfg.show_agents and cfg.multiagent.n_agents < 2:
        # Just broken (nothing wrong in theory)
        return False

    if cfg.model.name == "seqnca" and np.any(
        cfg.model.patch_width > cfg.task.obs_window
    ):
        return False

    # TODO: Only QMIX when multagent.

    # TODO: Potentially make sure that action space does not correspond to a level patch that is bigger than the
    # observation.

    return cfg


# def load_model(log_dir, n_tools=None, load_best=False):
#     if load_best:
#         name = "best"
#     else:
#         name = "latest"
#     model_path = os.path.join(log_dir, "{}_model.pkl".format(name))
#
#     if not os.path.exists(model_path):
#         model_path = os.path.join(log_dir, "{}_model.zip".format(name))
#
#     if not os.path.exists(model_path):
#         files = [f for f in os.listdir(log_dir) if ".pkl" in f or ".zip" in f]
#
#         if len(files) > 0:
#             # selects the last file listed by os.listdir
#             # What the fuck is up with the random thing
#             model_path = os.path.join(log_dir, np.random.choice(files))
#         else:
#             print("No models are saved at {}".format(model_path))
#             return None
# #           raise Exception("No models are saved at {}".format(model_path))
#     print("Loading model at {}".format(model_path))
#
#     if n_tools:
#         policy_kwargs = {"n_tools": n_tools}
#     else:
#         policy_kwargs = {}
#     model = PPO2.load(model_path, reset_num_timesteps=False)
#
#     return model


def max_exp_idx(exp_name):
    log_dir = os.path.join("../runs", exp_name)

    # Collect log directories corresponding to this experiment.
    log_files = glob.glob("{}*".format(log_dir))

    if len(log_files) == 0:
        n = 1
    else:
        # Get the IDs of past log directories, assign the next one to this experiment (should only apply when reloading!)
        log_ns = [re.search("_(\d+)(_log)?$", f).group(1) for f in log_files]
        n = max(log_ns)
    return int(n)


def parse_ppo_config(
    cfg: Config,
    agent_obs_space,
    log_dir,
    logger_type,
    stats_callbacks,
    # checkpoint_path_file,
    model_cfg,
    multiagent_config={},
    **kwargs,
):
    num_workers = kwargs.get("num_workers", 0)
    num_envs_per_worker = kwargs.get("num_envs_per_worker", 1)
    # eval_num_workers = kwargs.get('num_workers', 0)
    eval_num_workers = num_workers if cfg.evaluate else 0

    ppo_config = PPOConfig()
    ppo_config.environment(
        env="pcgrl",
        render_env=cfg.render,
        env_config={
            **cfg,  # Maybe env should get its own config? (A subset of the original?)
            "evaluation_env": False,
        },
        env_task_fn=set_map_fn,
        disable_env_checking=True,
    )
    ppo_config.framework("torch")
    ppo_config.rollouts(
        num_rollout_workers=num_workers,
        num_envs_per_worker=num_envs_per_worker,
    )
    ppo_config.training(
        model={
            "custom_model": "custom_model",
            "custom_model_config": {
                "dummy_env_obs_space": copy.copy(agent_obs_space),
                **model_cfg,
            },
        },
        lr=cfg.learning_rate,
        gamma=cfg.gamma,
        train_batch_size=cfg.train_batch_size,
    )
    # ppo_config.model(
    #     custom_model='custom_model',
    #     custom_model_config={
    #         "dummy_env_obs_space": copy.copy(agent_obs_space),
    #         **model_cfg,
    #     },
    # )
    ppo_config.evaluation(
        evaluation_interval=1
        if not cfg.evaluate
        else cfg.n_eval_episodes,  # meaningless if evaluating pre-trained agent (?)
        evaluation_duration_unit="episodes",
        evaluation_duration=cfg.n_eval_episodes
        if cfg.evaluate
        else max(1, eval_num_workers),
        evaluation_num_workers=eval_num_workers,
        evaluation_config={
            "env_config": {
                **cfg,
                "evaluation_env": True,
                "num_eval_envs": num_envs_per_worker * eval_num_workers,
            },
        },
    )
    ppo_config.debugging(
        logger_config={
            **logger_type,
            "logdir": log_dir,
        },
    )
    ppo_config.callbacks(
        stats_callbacks,
    )
    ppo_config.exploration(
        explore=True,
    )
    ppo_config.resources(num_gpus=cfg.hardware.n_gpu)

    #     ppo_config = {
    #         'env': 'pcgrl',
    #         **multiagent_config,
    #         'framework': 'torch',
    #         'num_workers': num_workers if not (cfg.evaluate or cfg.infer) else 0,
    #         'num_gpus': cfg.hardware.n_gpu,
    #         'env_config': {
    #             **cfg,  # Maybe env should get its own config? (A subset of the original?)
    #             "evaluation_env": False,
    #         },
    #         'num_envs_per_worker': num_envs_per_worker,
    #         'render_env': cfg.render,
    #         'lr': cfg.learning_rate,
    #         'gamma': cfg.gamma,
    #         'model': {
    #             'custom_model': 'custom_model',
    #             'custom_model_config': {
    #                 "dummy_env_obs_space": copy.copy(agent_obs_space),
    #             **model_cfg,
    #             },
    #         },
    #         # When training, eval for 1 episode every 100 train steps. If evaluating, evaluate for 100 episodes.
    #         "evaluation_interval": 1 if not cfg.evaluate else cfg.n_eval_episodes,  # meaningless if evaluating pre-trained agent (?)
    #         "evaluation_duration_unit": "episodes",
    #         "evaluation_duration": cfg.n_eval_episodes if cfg.evaluate else max(1, eval_num_workers),
    #         "evaluation_num_workers": eval_num_workers,
    #         "env_task_fn": set_map_fn,
    #         "evaluation_config": {
    #             "env_config": {
    #                 **cfg,
    #                 "evaluation_env": True,
    #                 "num_eval_envs": num_envs_per_worker * eval_num_workers,
    #             },
    #             "explore": True if cfg.infer else False,
    #             "render_env": cfg.render,
    #         },
    #         "logger_config": {
    #                 # "wandb": {
    #                     # "project": "PCGRL",
    #                     # "name": exp_name_id,
    #                     # "id": exp_name_id,
    #                     # "api_key_file": "~/.wandb_api_key"
    #             # },
    #             **logger_type,
    #             # Optional: Custom logdir (do not define this here
    #             # for using ~/ray_results/...).
    #             "logdir": log_dir,
    #         },
    # #       "exploration_config": {
    # #           "type": "Curiosity",
    # #       }
    # #       "log_level": "INFO",
    #         # "train_batch_size": 50,
    #         # "sgd_minibatch_size": 50,
    #         'callbacks': stats_callbacks,

    #         # To take random actions while changing all tiles at once seems to invite too much chaos.
    #         'explore': True,

    #         # `ray.tune` seems to need these spaces specified here.
    #         # 'observation_space': dummy_env.observation_space,
    #         # 'action_space': dummy_env.action_space,

    #         # 'create_env_on_driver': True,
    #         # 'checkpoint_path_file': checkpoint_path_file,
    #         # 'record_env': log_dir,
    #         'disable_env_checking': True,

    #         'train_batch_size': cfg.train_batch_size,
    #     }
    return ppo_config


def make_grouped_env(config):
    n_agents = config.multiagent.n_agents
    dummy_env = make_env(config)
    groups = {"group_1": list(dummy_env.observation_space.keys())}
    obs_space = Tuple(dummy_env.observation_space.values())
    act_space = Tuple(dummy_env.action_space.values())
    # import pdb; pdb.set_trace()
    register_env(
        "grouped_pcgrl",
        lambda config: wrappers.GroupedEnvironmentWrapper(
            make_env(config).with_agent_groups(
                groups, obs_space=obs_space, act_space=act_space
            )
        ),
    )


def parse_qmix_config(
    config,
    agent_obs_space,
    log_dir,
    logger_type,
    stats_callbacks,
    # checkpoint_path_file,
    model_cfg,
    multiagent_config={},
    **kwargs,
):
    # register grouped version of environment
    # import pdb; pdb.set_trace()
    make_grouped_env(config)
    num_workers = kwargs.get("num_workers", 0)
    num_envs_per_worker = kwargs.get("num_envs_per_worker", 1)
    eval_num_workers = kwargs.get("num_workers", 0)
    return {
        "env": "grouped_pcgrl",  # replace with grouped environment
        "rollout_fragment_length": 1,
        "train_batch_size": 32,
        "framework": "torch",
        "num_workers": num_workers if not (config.evaluate or config.infer) else 0,
        "num_gpus": 0,  # config.hardware.n_gpu GPU's don't work for QMIX
        "env_config": {
            **config,  # Maybe env should get its own config? (A subset of the original?)
            "evaluation_env": False,
        },
        #'mixer': 'qmix',
        "num_envs_per_worker": num_envs_per_worker,
        "render_env": config.render,
        "lr": config.learning_rate,
        "gamma": config.gamma,
        "model": {
            "custom_model": "custom_model",
            "custom_model_config": {
                "dummy_env_obs_space": copy.copy(agent_obs_space),
                **model_cfg,
            },
        },
        "evaluation_interval": 1 if config.evaluate else 1,
        "evaluation_duration": max(1, num_workers),
        "evaluation_duration_unit": "episodes",
        "evaluation_num_workers": eval_num_workers,
        # "env_task_fn": set_map_fn,
        "evaluation_config": {
            "env_config": {
                **config,
                "evaluation_env": True,
                "num_eval_envs": num_envs_per_worker * eval_num_workers,
            },
            "explore": True,
        },
        "logger_config": {
            # "wandb": {
            # "project": "PCGRL",
            # "name": exp_name_id,
            # "id": exp_name_id,
            # "api_key_file": "~/.wandb_api_key"
            # },
            **logger_type,
            # Optional: Custom logdir (do not define this here
            # for using ~/ray_results/...).
            "logdir": log_dir,
        },
        #       "exploration_config": {
        #           "type": "Curiosity",
        #       }
        #       "log_level": "INFO",
        # "train_batch_size": 50,
        # "sgd_minibatch_size": 50,
        "callbacks": stats_callbacks,
        # To take random actions while changing all tiles at once seems to invite too much chaos.
        "explore": True,
        # `ray.tune` seems to need these spaces specified here.
        # 'observation_space': dummy_env.observation_space,
        # 'action_space': dummy_env.action_space,
        # 'create_env_on_driver': True,
        # 'checkpoint_path_file': checkpoint_path_file,
        # 'record_env': log_dir,
        # 'stfu': True,
        "disable_env_checking": True,
    }


TrainerConfigParsers = {"PPO": parse_ppo_config, "QMIX": parse_qmix_config}


def which_device():
    """Returns the device on which to run the model"""
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    return device
