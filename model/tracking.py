import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import resnet
from torch.autograd import Variable

EPS = 0.003


def Fanin_init(size, fanin=None):
    fanin = fanin or size[0]
    v = 1. / np.sqrt(fanin)
    return torch.Tensor(size).uniform_(-v, v)


class TrackModel(nn.Module):

    def __init__(self, pretrained=True):
        super(TrackModel, self).__init__()
        self.feature_extractor = resnet.resnet18(pretrained=pretrained).cuda()
        self.actor = Actor(state_dim=256, action_space=2).cuda()
        self.critic = Critic(state_dim=256, action_dim=1).cuda()
        self.rnn = nn.LSTM(input_size=256, hidden_size=256, num_layers=1).cuda()

    def forward(self, imgs, action=None, hidden_prev=None, is_play=True):

        batch_size = imgs.size[0]
        # state = self.feature_extractor(img)
        # state = state[None,:,:]  # change the hidden state [batch, state_dim] -> [1, batch, state_dim]
        # hidden_pres = self.rnn(state, hidden_prev)
        # h0 = hidden_pres[0]

        if self.is_play:
            state = self.feature_extractor(imgs)
            state = state[None, :, :]  # change the hidden state [batch, state_dim] -> [1, batch, state_dim]
            hidden_pres = self.rnn(state, hidden_prev)
            h0 = hidden_pres[0].squeeze(0)
            action_prob, _ = self.actor(0)
            return action_prob, hidden_pres
        else:
            hiddens = []
            for i in range(batch_size):
                img = imgs[i,:,:,:].unsqueeze(0)
                state = self.feature_extractor(img) # 1*256
                state = state[None, :, :]  # change the hidden state [batch, state_dim] -> [1, batch, state_dim]
                hidden_pres = self.rnn(state, hidden_prev)
                h0 = hidden_pres[0].squeeze(0) # 1*256
                hidden_prev = hidden_pres
                hiddens.append(h0)
            hiddens = torch.cat(tuple(hiddens), 0)

            action_prob, action_logprob = self.actor(hiddens)
            value = self.critic(hiddens, action)

            return action_prob, action_logprob, hidden_pres, value

    def init_hidden_state(self, batch_size):
        return(Variable(torch.zeros(1, batch_size, self.hidden_size)).cuda(),
               Variable(torch.zeros(1, batch_size, self.hidden_size)).cuda())


class Critic(nn.Module):

    def __init__(self, state_dim, action_dim):
        """
        The network is to estimate the value of reward;

        Args:
        ----
        - state_dim: input hidden state dimensions, int,256
        - action_dim: input action dimension, int 1
        """
        super(Critic, self).__init__()

        self.state_dim = state_dim
        self.action_dim = action_dim

        self.fcs1 = nn.Linear(state_dim,256)
        self.fcs1.weight.data = Fanin_init(self.fcs1.weight.data.size())
        self.fcs2 = nn.Linear(256,128)
        self.fcs2.weight.data = Fanin_init(self.fcs2.weight.data.size())

        self.fca1 = nn.Linear(action_dim,128)
        self.fca1.weight.data = Fanin_init(self.fca1.weight.data.size())

        self.fc2 = nn.Linear(256,128)
        self.fc2.weight.data = Fanin_init(self.fc2.weight.data.size())

        self.fc3 = nn.Linear(128,1)
        self.fc3.weight.data.uniform_(-EPS,EPS)

    def forward(self, state, action):
        """
        returns Value function Q(s,a) obtained from critic network

        Args:
        ----
        - state:  Input state (Torch Variable : [n,state_dim] )
        - action: Input Action (Torch Variable : [n,action_dim]
        - Value:  Value function : Q(S,a) (Torch Variable : [n,1] ). The true rewards will lying in [0, 1]
        """
        s1 = F.relu(self.fcs1(state))
        s2 = F.relu(self.fcs2(s1))
        a1 = F.relu(self.fca1(action))
        x = torch.cat((s2,a1),dim=1)

        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        x = F.sigmoid(x)

        return x


class Actor(nn.Module):

    def __init__(self, state_dim, action_space):
        """
        :param state_dim: Dimension of input state (int)
        :param action_dim: Dimension of output action (int)
        """
        super(Actor, self).__init__()

        self.state_dim = state_dim
        self.action_dim = action_space

        self.fc1 = nn.Linear(state_dim,256)
        self.fc1.weight.data = Fanin_init(self.fc1.weight.data.size())

        self.fc2 = nn.Linear(256,128)
        self.fc2.weight.data = Fanin_init(self.fc2.weight.data.size())

        self.fc3 = nn.Linear(128,64)
        self.fc3.weight.data = Fanin_init(self.fc3.weight.data.size())

        self.fc4 = nn.Linear(64,action_space)
        self.fc4.weight.data.uniform_(-EPS,EPS)
        self.softmax = nn.Softmax(dim=1)
        self.logsoftmax = nn.LogSoftmax(dim=1)

    def forward(self, state):
        """
        returns policy function Pi(s) obtained from actor network
        this function is a gaussian prob distribution for all actions
        with mean lying in (-1,1) and sigma lying in (0,1)
        The sampled action can , then later be rescaled.

        Args:
        ----
        -state: input state (torch Variable: [n, state_dim])
        -action_prob, action_logporb: output probability and logsoftmax; [n,action_dim]
        """
        x = F.relu(self.fc1(state))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))

        # action = F.tanh(self.fc4(x))
        # action = action * self.action_lim
        x = self.fc4(x)
        action_prob = self.softmax(x)
        action_logprob = self.logsoftmax(x)

        return action_prob, action_logprob



