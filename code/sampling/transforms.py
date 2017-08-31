import os
import random
import math
import numpy as np
import scipy.ndimage as ndi

#from sklearn.base import BaseEstimator, TransformerMixin


class Compose(object):

    def __init__(self, transforms):
        self.transforms = transforms

    def _reset(self):
        for tx in self.transforms:
            tx._reset()

    def fit(self, X, y=None):
        for tx in self.transforms:
            tx.fit(X, y)

    def transform(self, X, y=None):
        for tx in self.transforms:
            X = tx.transform(X)
        return X


class LambdaTransform(object):

    def __init__(self, fn):
        self.fn = fn

    def transform(self, X, y=None):
        return self.fn(X)


class ExpandDims(object):

    def __init__(self, axis=-1):
        self.axis = axis

    def transform(self, X, y=None):
        return np.expand_dims(X, axis=self.axis)


class ToCategorical(object):

    def __init__(self, num_classes=None):
        self.num_classes = num_classes

    def transform(self, X, y=None):
        X = np.array(X, dtype='int').ravel()
        if not self.num_classes:
            self.num_classes = np.max(X) + 1
        n = X.shape[0]
        categorical = np.zeros((n, self.num_classes))
        categorical[np.arange(n), X] = 1
        return categorical


class TypeCast(object):
    def __init__(self, dtype):
        self.dtype = dtype

    def transform(self, X, y=None):
        return X.astype(self.dtype)



def transform_matrix_offset_center(matrix, x, y):
    o_x = float(x) / 2 + 0.5
    o_y = float(y) / 2 + 0.5
    offset_matrix = np.array([[1, 0, o_x], [0, 1, o_y], [0, 0, 1]])
    reset_matrix = np.array([[1, 0, -o_x], [0, 1, -o_y], [0, 0, 1]])
    transform_matrix = np.dot(np.dot(offset_matrix, matrix), reset_matrix)
    return transform_matrix

def apply_transform(x, transform, fill_mode='nearest', fill_value=0., channel_axis=-1):
    x = np.rollaxis(x, channel_axis, 0)
    x = x.astype('float32')
    transform = transform_matrix_offset_center(transform, x.shape[1], x.shape[2])
    final_affine_matrix = transform[:2, :2]
    final_offset = transform[:2, 2]
    channel_images = [ndi.interpolation.affine_transform(x_channel, 
        final_affine_matrix, final_offset, order=0, mode=fill_mode, 
        cval=fill_value) for x_channel in x]
    x = np.stack(channel_images, axis=0)
    x = np.rollaxis(x, 0, channel_axis+1)
    return x


class Affine(object):

    def __init__(self, 
                 rotation_range=None, 
                 translation_range=None,
                 shear_range=None, 
                 zoom_range=None, 
                 fill_mode='constant',
                 fill_value=0., 
                 target_fill_mode='nearest', 
                 target_fill_value=0.):
        """Perform an affine transforms with various sub-transforms, using
        only one interpolation and without having to instantiate each
        sub-transform individually.

        Arguments
        ---------
        rotation_range : one integer or float
            image will be rotated between (-degrees, degrees) degrees

        translation_range : a float or a tuple/list w/ 2 floats between [0, 1)
            first value:
                image will be horizontally shifted between 
                (-height_range * height_dimension, height_range * height_dimension)
            second value:
                Image will be vertically shifted between 
                (-width_range * width_dimension, width_range * width_dimension)

        shear_range : float
            radian bounds on the shear transform

        zoom_range : list/tuple with two floats between [0, infinity).
            first float should be less than the second
            lower and upper bounds on percent zoom. 
            Anything less than 1.0 will zoom in on the image, 
            anything greater than 1.0 will zoom out on the image.
            e.g. (0.7, 1.0) will only zoom in, 
                 (1.0, 1.4) will only zoom out,
                 (0.7, 1.4) will randomly zoom in or out

        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform
            ProTip : use 'nearest' for discrete images (e.g. segmentations)
                    and use 'constant' for continuous images

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        target_fill_mode : same as fill_mode, but for target image

        target_fill_value : same as fill_value, but for target image

        """
        self.transforms = []
        if rotation_range:
            rotation_tform = Rotate(rotation_range, lazy=True)
            self.transforms.append(rotation_tform)

        if translation_range:
            translation_tform = Translate(translation_range, lazy=True)
            self.transforms.append(translation_tform)

        if shear_range:
            shear_tform = Shear(shear_range, lazy=True)
            self.transforms.append(shear_tform) 

        if zoom_range:
            zoom_tform = Zoom(zoom_range, lazy=True)
            self.transforms.append(zoom_tform)

        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value

    def transform(self, X, y=None):
        # collect all of the lazily returned tform matrices
        tform_matrix = self.transforms[0](X)
        for tform in self.transforms[1:]:
            tform_matrix = np.dot(tform_matrix, tform(X)) 

        X = apply_transform(X, tform_matrix,
                            fill_mode=self.fill_mode, 
                            fill_value=self.fill_value)

        if y is not None:
            y = apply_transform(y, tform_matrix,
                fill_mode=self.target_fill_mode, 
                fill_value=self.target_fill_value)
            return X, y
        else:
            return X


class AffineCompose(object):

    def __init__(self, 
                 transforms, 
                 fill_mode='constant', 
                 fill_value=0., 
                 target_fill_mode='nearest', 
                 target_fill_value=0.):
        """Apply a collection of explicit affine transforms to an input image,
        and to a target image if necessary

        Arguments
        ---------
        transforms : list or tuple
            each element in the list/tuple should be an affine transform.
            currently supported transforms:
                - Rotate()
                - Translate()
                - Shear()
                - Zoom()

        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        """
        self.transforms = transforms
        # set transforms to lazy so they only return the tform matrix
        for t in self.transforms:
            t.lazy = True
        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value

    def transform(self, X, y=None):
        # collect all of the lazily returned tform matrices
        tform_matrix = self.transforms[0](X)
        for tform in self.transforms[1:]:
            tform_matrix = np.dot(tform_matrix, tform(X)) 

        X = apply_transform(X, tform_matrix,
                            fill_mode=self.fill_mode, 
                            fill_value=self.fill_value)

        if y is not None:
            y = apply_transform(y, tform_matrix,
                                fill_mode=self.target_fill_mode, 
                                fill_value=self.target_fill_value)
            return X, y
        else:
            return X


class Rotate(object):

    def __init__(self, 
                 rotation_range, 
                 fill_mode='constant', 
                 fill_value=0., 
                 target_fill_mode='nearest', 
                 target_fill_value=0., 
                 lazy=False):
        """Randomly rotate an image between (-degrees, degrees). If the image
        has multiple channels, the same rotation will be applied to each channel.

        Arguments
        ---------
        rotation_range : integer or float
            image will be rotated between (-degrees, degrees) degrees

        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        lazy    : boolean
            if true, perform the transform on the tensor and return the tensor
            if false, only create the affine transform matrix and return that
        """
        self.rotation_range = rotation_range
        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value
        self.lazy = lazy

    def transform(self, X, y=None):
        degree = random.uniform(-self.rotation_range, self.rotation_range)
        theta = math.pi / 180 * degree
        rotation_matrix = np.array([[math.cos(theta), -math.sin(theta), 0],
                                    [math.sin(theta), math.cos(theta), 0],
                                    [0, 0, 1]])
        if self.lazy:
            return rotation_matrix
        else:
            x_transformed = apply_transform(X, rotation_matrix, 
                                            fill_mode=self.fill_mode, 
                                            fill_value=self.fill_value)
            if y is not None:
                y_transformed = apply_transform(y, rotation_matrix,
                                                fill_mode=self.target_fill_mode, 
                                                fill_value=self.target_fill_value)
                return x_transformed, y_transformed
            else:
                return x_transformed


class Translate(object):

    def __init__(self, 
                 translation_range, 
                 fill_mode='constant',
                 fill_value=0., 
                 target_fill_mode='nearest', 
                 target_fill_value=0., 
                 lazy=False):
        """Randomly translate an image some fraction of total height and/or
        some fraction of total width. If the image has multiple channels,
        the same translation will be applied to each channel.

        Arguments
        ---------
        translation_range : two floats between [0, 1) 
            first value:
                fractional bounds of total height to shift image
                image will be horizontally shifted between 
                (-height_range * height_dimension, height_range * height_dimension)
            second value:
                fractional bounds of total width to shift image 
                Image will be vertically shifted between 
                (-width_range * width_dimension, width_range * width_dimension)

        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        lazy    : boolean
            if true, perform the transform on the tensor and return the tensor
            if false, only create the affine transform matrix and return that
        """
        if isinstance(translation_range, float):
            translation_range = (translation_range, translation_range)
        self.height_range = translation_range[0]
        self.width_range = translation_range[1]
        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value
        self.lazy = lazy

    def transform(self, X, y=None):
        # height shift
        if self.height_range > 0:
            tx = random.uniform(-self.height_range, self.height_range) * X.shape[0]
        else:
            tx = 0
        # width shift
        if self.width_range > 0:
            ty = random.uniform(-self.width_range, self.width_range) * X.shape[1]
        else:
            ty = 0

        translation_matrix = np.array([[1, 0, tx],
                                       [0, 1, ty],
                                       [0, 0, 1]])
        if self.lazy:
            return translation_matrix
        else:
            x_transformed = apply_transform(X, translation_matrix, 
                                            fill_mode=self.fill_mode, 
                                            fill_value=self.fill_value)
            if y is not None:
                y_transformed = apply_transform(y, translation_matrix,
                                                fill_mode=self.target_fill_mode, 
                                                fill_value=self.target_fill_value)
                return x_transformed, y_transformed
            else:
                return x_transformed


class Shear(object):

    def __init__(self, 
                 shear_range, 
                 fill_mode='constant', 
                 fill_value=0., 
                 target_fill_mode='nearest', 
                 target_fill_value=0., 
                 lazy=False):
        """Randomly shear an image with radians (-shear_range, shear_range)

        Arguments
        ---------
        shear_range : float
            radian bounds on the shear transform
        
        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        lazy    : boolean
            if true, perform the transform on the tensor and return the tensor
            if false, only create the affine transform matrix and return that
        """
        self.shear_range = shear_range
        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value
        self.lazy = lazy

    def transform(self, X, y=None):
        shear = random.uniform(-self.shear_range, self.shear_range)
        shear_matrix = np.array([[1, -math.sin(shear), 0],
                                 [0, math.cos(shear), 0],
                                 [0, 0, 1]])
        if self.lazy:
            return shear_matrix
        else:
            x_transformed = apply_transform(X, shear_matrix, 
                                            fill_mode=self.fill_mode, 
                                            fill_value=self.fill_value)
            if y is not None:
                y_transformed = apply_transform(y, shear_matrix,
                                                fill_mode=self.target_fill_mode, 
                                                fill_value=self.target_fill_value)
                return x_transformed, y_transformed
            else:
                return x_transformed

      

class Zoom(object):

    def __init__(self, 
                 zoom_range, 
                 fill_mode='constant', 
                 fill_value=0, 
                 target_fill_mode='nearest', 
                 target_fill_value=0., 
                 lazy=False):
        """Randomly zoom in and/or out on an image 

        Arguments
        ---------
        zoom_range : tuple or list with 2 values, both between (0, infinity)
            lower and upper bounds on percent zoom. 
            Anything less than 1.0 will zoom in on the image, 
            anything greater than 1.0 will zoom out on the image.
            e.g. (0.7, 1.0) will only zoom in, 
                 (1.0, 1.4) will only zoom out,
                 (0.7, 1.4) will randomly zoom in or out

        fill_mode : string in {'constant', 'nearest'}
            how to fill the empty space caused by the transform

        fill_value : float
            the value to fill the empty space with if fill_mode='constant'

        lazy    : boolean
            if true, perform the transform on the tensor and return the tensor
            if false, only create the affine transform matrix and return that
        """
        if not isinstance(zoom_range, list) and not isinstance(zoom_range, tuple):
            raise ValueError('zoom_range must be tuple or list with 2 values')
        self.zoom_range = zoom_range
        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.target_fill_mode = target_fill_mode
        self.target_fill_value = target_fill_value
        self.lazy = lazy

    def transform(self, X, y=None):
        zx = random.uniform(self.zoom_range[0], self.zoom_range[1])
        zy = random.uniform(self.zoom_range[0], self.zoom_range[1])
        zoom_matrix = np.array([[zx, 0, 0],
                                [0, zy, 0],
                                [0, 0, 1]])
        if self.lazy:
            return zoom_matrix
        else:
            x_transformed = apply_transform(X, zoom_matrix, 
                                            fill_mode=self.fill_mode, 
                                            fill_value=self.fill_value)
            if y is not None:
                y_transformed = apply_transform(y, zoom_matrix,
                                                fill_mode=self.target_fill_mode, 
                                                fill_value=self.target_fill_value)
                return x_transformed, y_transformed
            else:
                return x_transformed


