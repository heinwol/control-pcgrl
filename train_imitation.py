import glob
import os
import shutil
import hydra
from ray import air, tune
from ray.rllib.algorithms.bc import BCConfig, BC
from ray.rllib.algorithms.marwil import MARWILConfig, MARWIL
from ray.rllib.models import ModelCatalog
from ray.tune.registry import register_env

from control_pcgrl.configs.config import Config, PoDConfig
from control_pcgrl.il.utils import make_pod_env
from control_pcgrl.il.wrappers import obfuscate_observation
from control_pcgrl.rl.envs import make_env
from control_pcgrl.rl.models import CustomFeedForwardModel
from control_pcgrl.rl.utils import validate_config


@hydra.main(config_path="control_pcgrl/configs", config_name="pod")
def main(cfg: PoDConfig):
    cfg = validate_config(cfg)
    if cfg is False:
        print("Invalid config!")
        return

    traj_dir = os.path.join(cfg.log_dir, "repair-paths")

    register_env("pcgrl", make_env)
    model_cls = CustomFeedForwardModel
    ModelCatalog.register_custom_model("custom_model", model_cls)

    if cfg.offline_algo == "BC":
        algo_config = BCConfig()
    elif cfg.offline_algo == "MARWIL":
        algo_config = MARWILConfig()
    else:
        raise ValueError(f"Invalid offline algorithm: {cfg.offline_algo}")

    algo_config.model = {
        "custom_model": "custom_model",
        "custom_model_config": {},
    }

    # Print out some default values.
    print(algo_config.beta)

    # Update the config object.
    algo_config.training(
        # lr=tune.grid_search([0.001, 0.0001]), beta=0.0
        lr=0.001,
    )

    # Get all json files in the directory
    traj_glob = os.path.join(traj_dir, "*.json")

    # Set the config object's data path.
    # Run this from the ray directory root.
    algo_config.offline_data(
        # input_="./tmp/demo-out/output-2023-0"
        # input_=os.path.join(cfg.log_dir, "demo-out")
        input_=traj_glob,
    )

    # Set the config object's env, used for evaluation.
    algo_config.environment(env="pcgrl")
    algo_config.env_config = {**cfg}

    algo_config.framework("torch")

    il_log_dir = "il_logs"
    exp_name = cfg.offline_algo

    exp_dir = os.path.join(il_log_dir, exp_name)

    if not cfg.overwrite and os.path.exists(exp_dir):
        tuner = tune.Tuner.restore(exp_dir)
    else:
        shutil.rmtree(exp_dir, ignore_errors=True)

        run_config = air.RunConfig(
            checkpoint_config=air.CheckpointConfig(
                checkpoint_at_end=True,
                checkpoint_frequency=10,
                num_to_keep=2,
            ),
            local_dir=il_log_dir,
        )

        tuner = tune.Tuner(
            cfg.offline_algo,
            # "BC",
            param_space=algo_config.to_dict(),
            tune_config=tune.TuneConfig(
                metric="info/learner/default_policy/learner_stats/policy_loss",
                mode="min",
            ),
            run_config=run_config,
        )

    if cfg.infer:
        algo_cls = BC if cfg.offline_algo == "BC" else MARWIL
        best_result = tuner.get_results().get_best_result()
        ckpt = best_result.best_checkpoints[0][0]
        bc_model = algo_cls.from_checkpoint(ckpt)
        print(f"Restored from checkpoint {ckpt}")
        # bc_model.evaluate()

        env = make_pod_env(cfg)

        while True:
            obs, info = env.reset()
            done, truncated = False, False
            while not done and not truncated:
                # action = bc_model.compute_single_action(obfuscate_observation(obs), explore=False)
                action = bc_model.compute_single_action((obs), explore=True)
                obs, reward, done, truncated, info = env.step(action)
                env.render()

    else:
        # Use to_dict() to get the old-style python config dict
        # when running with tune.
        result = tuner.fit()


if __name__ == "__main__":
    main()
