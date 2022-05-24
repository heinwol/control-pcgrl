from pdb import set_trace as TT
from gym.utils import seeding
from gym_pcgrl.envs.helper_3D import gen_random_map
import numpy as np

"""
The base class of all the 3D representations

map in repr are np.array of numbers
"""
class Representation3D:
    """
    The base constructor where all the representation variable are defined with default values
    """
    def __init__(self, border_tile=1):
        self._random_start = True
        self._map = None
        self._old_map = None
        self._border_tile = border_tile

        self.seed()

    """
    Seeding the used random variable to get the same result. If the seed is None,
    it will seed it with random start.

    Parameters:
        seed (int): the starting seed, if it is None a random seed number is used.

    Returns:
        int: the used seed (same as input if not None)
    """
    def seed(self, seed=None):
        self._random, seed = seeding.np_random(seed)
        return seed

    """
    Resets the current representation

    Parameters:
        length (int): the generated map length
        width (int): the generated map width
        height (int): the generated map height
        prob (dict(int,float)): the probability distribution of each tile value
    """
    def reset(self, length, width, height, prob):
        if self._random_start or self._old_map is None:
            self._map = gen_random_map(self._random, length, width, height, prob)
            self._bordered_map = np.empty((length +2, width + 2, height + 2), dtype=np.int)
            self._bordered_map.fill(self._border_tile)
            self._bordered_map[1:-1, 1:-1, 1:-1] = self._map
            self._old_map = self._map.copy()
        else:
            self._map = self._old_map.copy()

    """
    Adjust current representation parameter

    Parameters:
        random_start (boolean): if the system will restart with a new map or the previous map
    """
    def adjust_param(self, **kwargs):
        self._random_start = kwargs.get('random_start', self._random_start)

    """
    Gets the action space used by the representation

    Parameters:
        length: the current map length
        width: the current map width
        height: the current map height
        num_tiles: the total number of the tile values

    Returns:
        ActionSpace: the action space used by that representation
    """
    def get_action_space(self, length, width, height, num_tiles):
        raise NotImplementedError('get_action_space is not implemented')

    """
    Get the observation space used by the representation

    Parameters:
        length: the current map length
        width: the current map width
        height: the current map height
        num_tiles: the total number of the tile values

    Returns:
        ObservationSpace: the observation space used by that representation
    """
    def get_observation_space(self, length, width, height, num_tiles):
        raise NotImplementedError('get_observation_space is not implemented')

    """
    Get the current representation observation object at the current moment

    Returns:
        observation: the current observation at the current moment
    """
    def get_observation(self):
        raise NotImplementedError('get_observation is not implemented')

    """
    Update the representation with the current action

    Parameters:
        action: an action that is used to advance the environment (same as action space)

    Returns:
        boolean: True if the action change the map, False if nothing changed
    """
    def update(self, action):
        raise NotImplementedError('update is not implemented')

    """
    Modify the level image with any special modification based on the representation

    Parameters:
        lvl_image (img): the current level_image without modifications
        tile_size (int): the size of tiles in pixels used in the lvl_image
        border_size ((int,int)): an offeset in tiles if the borders are not part of the level

    Returns:
        img: the modified level image
    """
    def render(self, map):
        # return lvl_image
        return
