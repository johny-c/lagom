import numpy as np

import pytest

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from torch.distributions import Categorical
from torch.distributions import Normal
from torch.distributions import Independent

from lagom.networks import Module
from lagom.networks import linear_lr_scheduler
from lagom.networks import ortho_init
from lagom.networks import make_fc
from lagom.networks import make_cnn
from lagom.networks import make_transposed_cnn
from lagom.networks import make_rnncell
from lagom.networks import CategoricalHead
from lagom.networks import DiagGaussianHead


class TestMakeBlocks(object):
    def test_make_fc(self):
        # Single layer
        fc = make_fc(3, [4])
        assert len(fc) == 1
        
        # Multiple layers
        fc = make_fc(3, [4, 5, 6])
        assert len(fc) == 3
        
        # Raise Exception
        with pytest.raises(AssertionError):
            make_fc(3, 4)
            
    def test_make_cnn(self):
        # Single layer
        cnn = make_cnn(input_channel=3, channels=[16], kernels=[4], strides=[2], paddings=[1])
        assert len(cnn) == 1
        
        # Multiple layers
        cnn = make_cnn(input_channel=3, channels=[16, 32, 64], kernels=[4, 3, 3], strides=[2, 1, 1], paddings=[2, 1, 0])
        assert len(cnn) == 3
        
        # Raise Exception
        with pytest.raises(AssertionError):
            # Non-list
            make_cnn(input_channel=3, channels=[16], kernels=4, strides=[2], paddings=[1])
        with pytest.raises(AssertionError):
            # Inconsistent length
            make_cnn(input_channel=3, channels=[16], kernels=[4, 2], strides=[2], paddings=[1])
            
    def test_make_transposed_cnn(self):
        # Single layer
        transposed_cnn = make_transposed_cnn(input_channel=3, 
                                             channels=[16], 
                                             kernels=[4], 
                                             strides=[2], 
                                             paddings=[1], 
                                             output_paddings=[1])
        assert len(transposed_cnn) == 1
        
        # Multiple layers
        transposed_cnn = make_transposed_cnn(input_channel=3, 
                                     channels=[16, 32, 64], 
                                     kernels=[4, 3, 3], 
                                     strides=[2, 1, 1], 
                                     paddings=[2, 1, 0],
                                     output_paddings=[3, 1, 0])
        assert len(transposed_cnn) == 3
        
        # Raise Exception
        with pytest.raises(AssertionError):
            # Non-list
            make_transposed_cnn(input_channel=3, 
                                channels=[16], 
                                kernels=[4], 
                                strides=2, 
                                paddings=[1], 
                                output_paddings=[1])
        with pytest.raises(AssertionError):
            # Inconsistent length
            make_transposed_cnn(input_channel=3, 
                                channels=[16], 
                                kernels=[4], 
                                strides=[2, 1], 
                                paddings=[1], 
                                output_paddings=[1])
    
    @pytest.mark.parametrize('cell_type', ['RNNCell', 'LSTMCell', 'GRUCell'])
    def test_make_rnncell(self, cell_type):
        # Single layer
        rnn = make_rnncell(cell_type=cell_type, input_dim=3, hidden_sizes=[16])
        assert isinstance(rnn, nn.ModuleList)
        assert all(isinstance(i, nn.RNNCellBase) for i in rnn)
        assert len(rnn) == 1
        
        # Multiple layers
        rnn = make_rnncell(cell_type=cell_type, input_dim=3, hidden_sizes=[16, 32])
        assert isinstance(rnn, nn.ModuleList)
        assert all(isinstance(i, nn.RNNCellBase) for i in rnn)
        assert len(rnn) == 2
        
        # Raise exceptions
        with pytest.raises(ValueError):  # non-defined rnn cell type
            make_rnncell('randomrnn', 3, [16])
        with pytest.raises(AssertionError):  # non-list hidden sizes
            make_rnncell(cell_type, 3, 16)


class TestInit(object):
    def test_ortho_init(self):
        # Linear
        a = nn.Linear(2, 3)
        ortho_init(a, weight_scale=1000., constant_bias=10.)
        assert a.weight.max().item() > 50.
        assert np.allclose(a.bias.detach().numpy(), 10.)
        ortho_init(a, nonlinearity='relu')
        
        # Conv2d
        a = nn.Conv2d(2, 3, 3)
        ortho_init(a, weight_scale=1000., constant_bias=10.)
        assert a.weight.max().item() > 100.
        assert np.allclose(a.bias.detach().numpy(), 10.)
        ortho_init(a, nonlinearity='relu')
        
        # LSTM
        a = nn.LSTM(2, 3, 2)
        ortho_init(a, weight_scale=1000., constant_bias=10.)
        assert a.weight_hh_l0.max().item() > 100.
        assert a.weight_hh_l1.max().item() > 100.
        assert a.weight_ih_l0.max().item() > 100.
        assert a.weight_ih_l1.max().item() > 100.
        assert np.allclose(a.bias_hh_l0.detach().numpy(), 10.)
        assert np.allclose(a.bias_hh_l1.detach().numpy(), 10.)
        assert np.allclose(a.bias_ih_l0.detach().numpy(), 10.)
        assert np.allclose(a.bias_ih_l1.detach().numpy(), 10.)
        
        # LSTMCell
        a = nn.LSTMCell(3, 2)
        ortho_init(a, weight_scale=1000., constant_bias=10.)
        assert a.weight_hh.max().item() > 100.
        assert a.weight_ih.max().item() > 100.
        assert np.allclose(a.bias_hh.detach().numpy(), 10.)
        assert np.allclose(a.bias_ih.detach().numpy(), 10.)


@pytest.mark.parametrize('method', ['Adam', 'RMSprop', 'Adamax'])
@pytest.mark.parametrize('N', [1, 10, 50, 100])
@pytest.mark.parametrize('min_lr', [3e-4, 6e-5])
@pytest.mark.parametrize('initial_lr', [1e-3, 7e-4])
def test_linear_lr_scheduler(method, N, min_lr, initial_lr):
    net = nn.Linear(30, 16)
    if method == 'Adam':
        optimizer = optim.Adam(net.parameters(), lr=initial_lr)
    elif method == 'RMSprop':
        optimizer = optim.RMSprop(net.parameters(), lr=initial_lr)
    elif method == 'Adamax':
        optimizer = optim.Adamax(net.parameters(), lr=initial_lr)
    lr_scheduler = linear_lr_scheduler(optimizer, N, min_lr)
    assert lr_scheduler.base_lrs[0] == initial_lr
    
    for i in range(200):
        lr_scheduler.step()
        assert lr_scheduler.get_lr()[0] >= min_lr
    assert lr_scheduler.get_lr()[0] == min_lr       
    
    
@pytest.mark.parametrize('feature_dim', [5, 10, 30])
@pytest.mark.parametrize('batch_size', [1, 16, 32])
@pytest.mark.parametrize('num_action', [1, 4, 10])
def test_categorical_head(feature_dim, batch_size, num_action):
    action_head = CategoricalHead(feature_dim, num_action, torch.device('cpu'))
    assert isinstance(action_head, Module)
    assert action_head.feature_dim == feature_dim
    assert action_head.num_action == num_action
    assert action_head.device.type == 'cpu'
    dist = action_head(torch.randn(batch_size, feature_dim))
    assert isinstance(dist, Categorical)
    assert dist.batch_shape == (batch_size,)
    assert dist.probs.shape == (batch_size, num_action)
    x = dist.sample()
    assert x.shape == (batch_size,)
    
    
@pytest.mark.parametrize('batch_size', [1, 32])
@pytest.mark.parametrize('feature_dim', [5, 20])
@pytest.mark.parametrize('action_dim', [1, 4])
@pytest.mark.parametrize('std0', [0.21, 0.5, 1.0])
@pytest.mark.parametrize('std_style', ['exp', 'softplus', 'sigmoidal'])
@pytest.mark.parametrize('std_range', [(0.01, 1.2), (0.2, 1.5)])
@pytest.mark.parametrize('beta', [0.5, 2.0])
def test_diag_gaussian_head(batch_size, feature_dim, action_dim, std0, std_style, std_range, beta):
    device = torch.device('cpu')
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, -0.5, std_style, std_range, beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'softexp', std_range, beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'sigmoidal', [0.1, 0.5, 1.0], beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'sigmoidal', [-0.5, 1.0], beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'sigmoidal', [0.5, 0.1], beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'sigmoidal', std_range, None)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, 0.009, 'sigmoidal', std_range, beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'exp', std_range, beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'exp', std_range, None)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'softplus', std_range, beta)
    with pytest.raises(AssertionError):
        DiagGaussianHead(feature_dim, action_dim, device, std0, 'softplus', None, beta)
    
    def _basic_check(action_head):
        assert action_head.feature_dim == feature_dim
        assert action_head.action_dim == action_dim
        assert action_head.device.type == 'cpu'
        assert action_head.std0 == std0
        assert action_head.std_style == std_style
        assert action_head.eps == 1e-4
        assert isinstance(action_head.mean_head, nn.Linear)
        assert isinstance(action_head.logvar_head, nn.Parameter)
        
    def _dist_check(action_dist):
        assert isinstance(action_dist, Independent)
        assert isinstance(action_dist.base_dist, Normal)
        assert action_dist.batch_shape == (batch_size,)
        action = action_dist.sample()
        assert action.shape == (batch_size, action_dim)
    
    if std_style in ['exp', 'softplus']:
        action_head = DiagGaussianHead(feature_dim, action_dim, device, std0, std_style, None, None)
        assert action_head.std_range is None
        assert action_head.beta is None
    else:  # sigmoidal
        action_head = DiagGaussianHead(feature_dim, action_dim, device, std0, std_style, std_range, beta)
        assert action_head.std_range is not None
        assert action_head.beta is not None
        
    _basic_check(action_head)
    action_dist = action_head(torch.randn(batch_size, feature_dim))
    _dist_check(action_dist)
    assert torch.allclose(action_dist.base_dist.stddev, torch.tensor(std0))
