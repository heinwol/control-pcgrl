import os
from pathlib import Path
from pdb import set_trace as TT
import numpy as np
from PIL import Image
from control_pcgrl.configs.config import Config
from control_pcgrl.envs.probs.problem import PROB_DIR, Problem
from control_pcgrl.envs.helper import (
    get_range_reward,
    get_tile_locations,
    calc_num_regions,
    calc_certain_tile,
    run_dijkstra,
    get_path_coords,
)

"""
Generate a fully connected GVGAI zelda level where the player can reach key then the door.

Args:
    target_enemy_dist: enemies should be at least this far from the player on spawn
"""


class ZeldaProblem(Problem):
    """
    The constructor is responsible of initializing all the game parameters
    """

    _tile_types = [
        "empty",
        "solid",
        "player",
        "key",
        "door",
        "bat",
        "scorpion",
        "spider",
    ]

    def __init__(self, cfg: Config):
        super().__init__(cfg=cfg)
        self.path_length = 0
        self.path = []
        self._prob = {
            "empty": 0.58,
            "solid": 0.3,
            "player": 0.02,
            "key": 0.02,
            "door": 0.02,
            "bat": 0.02,
            "scorpion": 0.02,
            "spider": 0.02,
        }
        self._border_tile = "solid"

        self._max_enemies = 5

        self._target_enemy_dist = 4
        self._target_path = 16

        self._reward_weights = {
            "player": 3,
            "key": 3,
            "door": 3,
            "regions": 5,
            "enemies": 1,
            "nearest-enemy": 2,
            "path-length": 1,
        }

        # self.render_path = False

    """
    Adjust the parameters for the current problem

    Parameters:
        width (int): change the width of the problem level
        height (int): change the height of the problem level
        probs (dict(string, float)): change the probability of each tile
        intiialization, the names are "empty", "solid"
        target_path (int): the current path length that the episode turn when it reaches
        rewards (dict(string,float)): the weights of each reward change between the new_stats and old_stats
    """

    def adjust_param(self, **kwargs):
        super().adjust_param(**kwargs)

        self._max_enemies = kwargs.get("max_enemies", self._max_enemies)

        self._target_enemy_dist = kwargs.get(
            "target_enemy_dist", self._target_enemy_dist
        )
        self._target_path = kwargs.get("target_path", self._target_path)
        # self.render_path = kwargs.get('render') or kwargs.get('render_path', self.render_path)
        rewards = kwargs.get("rewards")
        if rewards is not None:
            for t in rewards:
                if t in self._reward_weights:
                    self._reward_weights[t] = rewards[t]

    """
    Get the current stats of the map

    Returns:
        dict(string,any): stats of the current map to be used in the reward, episode_over, debug_info calculations.
        The used status are "reigons": number of connected empty tiles, "path-length": the longest path across the map
    """

    def get_stats(self, map, lenient_paths=False):
        self.path = []
        map_locations = get_tile_locations(map, self.get_tile_types())
        map_stats = {
            "player": calc_certain_tile(map_locations, ["player"]),
            "key": calc_certain_tile(map_locations, ["key"]),
            "door": calc_certain_tile(map_locations, ["door"]),
            "enemies": calc_certain_tile(map_locations, ["bat", "spider", "scorpion"]),
            "regions": calc_num_regions(
                map,
                map_locations,
                ["empty", "player", "key", "bat", "spider", "scorpion"],
            ),
            "nearest-enemy": 0,
            "path-length": 0,
        }
        if map_stats["player"] == 1 and map_stats["regions"] == 1:
            p_x, p_y = map_locations["player"][0]
            enemies = []
            enemies.extend(map_locations["spider"])
            enemies.extend(map_locations["bat"])
            enemies.extend(map_locations["scorpion"])
            if len(enemies) > 0:
                # NOTE: for evo-pcgrl, we don't want these super-high nearest-enemy scores from when
                # the player is cornered behind a key (it distorts our map of elites), so we make key passable
                dijkstra, _ = run_dijkstra(
                    p_x,
                    p_y,
                    map,
                    ["key", "empty", "player", "bat", "spider", "scorpion"],
                )
                #               dijkstra,_ = run_dijkstra(p_x, p_y, map, ["empty", "player", "bat", "spider", "scorpion"])
                min_dist = self._width * self._height
                for e_x, e_y in enemies:
                    if dijkstra[e_y][e_x] > 0 and dijkstra[e_y][e_x] < min_dist:
                        min_dist = dijkstra[e_y][e_x]
                map_stats["nearest-enemy"] = min_dist
            if map_stats["key"] == 1 and map_stats["door"] == 1:
                k_x, k_y = map_locations["key"][0]
                d_x, d_y = map_locations["door"][0]

                # start point is people
                dijkstra_k, _ = run_dijkstra(
                    p_x,
                    p_y,
                    map,
                    ["empty", "key", "player", "bat", "spider", "scorpion"],
                )
                map_stats["path-length"] += dijkstra_k[k_y][k_x]

                # start point is key
                dijkstra_d, _ = run_dijkstra(
                    k_x,
                    k_y,
                    map,
                    ["empty", "player", "key", "door", "bat", "spider", "scorpion"],
                )
                map_stats["path-length"] += dijkstra_d[d_y][d_x]
                if self.render_path:
                    # end point is key
                    self.path = np.hstack(
                        (
                            get_path_coords(dijkstra_k, init_coords=(k_y, k_x)),
                            get_path_coords(dijkstra_d, init_coords=(d_y, d_x)),
                        )
                    )
                    # end point is door
        self.path_length = map_stats["path-length"]
        return map_stats

    """
    Get the current game reward between two stats

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        float: the current reward due to the change between the old map stats and the new map stats
    """

    def get_reward(self, new_stats, old_stats):
        # longer path is rewarded and less number of regions is rewarded
        rewards = {
            "player": get_range_reward(new_stats["player"], old_stats["player"], 1, 1),
            "key": get_range_reward(new_stats["key"], old_stats["key"], 1, 1),
            "door": get_range_reward(new_stats["door"], old_stats["door"], 1, 10),
            "enemies": get_range_reward(
                new_stats["enemies"], old_stats["enemies"], 2, self._max_enemies
            ),
            "regions": get_range_reward(
                new_stats["regions"], old_stats["regions"], 1, 1
            ),
            "nearest-enemy": get_range_reward(
                new_stats["nearest-enemy"],
                old_stats["nearest-enemy"],
                self._target_enemy_dist,
                np.inf,
            ),
            "path-length": get_range_reward(
                new_stats["path-length"], old_stats["path-length"], np.inf, np.inf
            ),
        }
        # calculate the total reward
        return (
            rewards["player"] * self._reward_weights["player"]
            + rewards["key"] * self._reward_weights["key"]
            + rewards["door"] * self._reward_weights["door"]
            + rewards["enemies"] * self._reward_weights["enemies"]
            + rewards["regions"] * self._reward_weights["regions"]
            + rewards["nearest-enemy"] * self._reward_weights["nearest-enemy"]
            + rewards["path-length"] * self._reward_weights["path-length"]
        )

    """
    Uses the stats to check if the problem ended (episode_over) which means reached
    a satisfying quality based on the stats

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        boolean: True if the level reached satisfying quality based on the stats and False otherwise
    """

    def get_episode_over(self, new_stats, old_stats):
        return (
            new_stats["nearest-enemy"] >= self._target_enemy_dist
            and new_stats["path-length"] >= self._target_path
        )

    """
    Get any debug information need to be printed

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        dict(any,any): is a debug information that can be used to debug what is
        happening in the problem
    """

    def get_debug_info(self, new_stats, old_stats):
        return {
            "player": new_stats["player"],
            "key": new_stats["key"],
            "door": new_stats["door"],
            "enemies": new_stats["enemies"],
            "regions": new_stats["regions"],
            "nearest-enemy": new_stats["nearest-enemy"],
            "path-length": new_stats["path-length"],
        }

    def init_graphics(self):
        if self.GVGAI_SPRITES:
            self._graphics = {
                "empty": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/floor3.png"
                ).convert("RGBA"),
                "solid": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/wall3.png"
                ).convert("RGBA"),
                "player": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/swordman1_0.png"
                ).convert("RGBA"),
                "key": Image.open(os.path.dirname(__file__) + "/sprites/oryx/key2.png")
                .convert("RGBA")
                .resize((24, 24)),
                "door": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/doorclosed1.png"
                ).convert("RGBA"),
                "spider": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/spider1.png"
                ).convert("RGBA"),
                "bat": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/bat2.png"
                ).convert("RGBA"),
                "scorpion": Image.open(
                    os.path.dirname(__file__) + "/sprites/oryx/scorpion1.png"
                ).convert("RGBA"),
                "path": Image.open(
                    os.path.dirname(__file__) + "/sprites/newset/snowmanchest.png"
                ).convert("RGBA"),
            }
        else:
            self._graphics = {
                "empty": Image.open(PROB_DIR + "/common/empty.png").convert("RGBA"),
                "solid": Image.open(PROB_DIR + "/common/solid.png").convert("RGBA"),
                "player": Image.open(
                    os.path.dirname(__file__) + "/zelda/player.png"
                ).convert("RGBA"),
                "key": Image.open(os.path.dirname(__file__) + "/zelda/key.png").convert(
                    "RGBA"
                ),
                "door": Image.open(
                    os.path.dirname(__file__) + "/zelda/door.png"
                ).convert("RGBA"),
                "spider": Image.open(
                    os.path.dirname(__file__) + "/zelda/spider.png"
                ).convert("RGBA"),
                "bat": Image.open(os.path.dirname(__file__) + "/zelda/bat.png").convert(
                    "RGBA"
                ),
                "scorpion": Image.open(
                    os.path.dirname(__file__) + "/zelda/scorpion.png"
                ).convert("RGBA"),
                "path": Image.open(PROB_DIR + "/common/path_g.png").convert("RGBA"),
            }

    """
    Get an image on how the map will look like for a specific map

    Parameters:
        map (string[][]): the current game map

    Returns:
        Image: a pillow image on how the map will look like using the binary graphics
    """

    def render(self, map):
        if self._graphics is None:
            self.init_graphics()
        return super().render(map, render_path=self.path)
