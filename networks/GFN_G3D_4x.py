import torch
import torch.nn as nn
import math
import torch.cuda
from .ridnet import RIDNET


class _ResBLockDB(nn.Module):
    def __init__(self, inchannel, outchannel, stride=1):
        super(_ResBLockDB, self).__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(inchannel, outchannel, 3, stride, 1, bias=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(outchannel, outchannel, 3, stride, 1, bias=True)
        )
        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def forward(self, x):
        out = self.layers(x)
        residual = x
        out = torch.add(residual, out)
        return out


class _ResBlockSR(nn.Module):
    def __init__(self, inchannel, outchannel, stride=1):
        super(_ResBlockSR, self).__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(inchannel, outchannel, 3, stride, 1, bias=True),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(outchannel, outchannel, 3, stride, 1, bias=True)
        )
        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def forward(self, x):
        out = self.layers(x)
        residual = x
        out = torch.add(residual, out)
        return out


class _DeblurringMoudle(nn.Module):
    def __init__(self):
        super(_DeblurringMoudle, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, (7, 7), 1, padding=3)
        self.relu = nn.LeakyReLU(0.2, inplace=True)
        self.resBlock1 = self._makelayers(64, 64, 6)
        self.conv2 = nn.Sequential(
            nn.Conv2d(64, 128, (3, 3), 2, 1),
            nn.ReLU(inplace=True)
        )
        self.resBlock2 = self._makelayers(128, 128, 6)
        self.conv3 = nn.Sequential(
            nn.Conv2d(128, 256, (3, 3), 2, 1),
            nn.ReLU(inplace=True)
        )
        self.resBlock3 = self._makelayers(256, 256, 6)
        self.deconv1 = nn.Sequential(
            nn.ConvTranspose2d(256, 128, (4, 4), 2, padding=1),
            nn.ReLU(inplace=True)
        )
        self.deconv2 = nn.Sequential(
            nn.ConvTranspose2d(128, 64, (4, 4), 2, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, (7, 7), 1, padding=3)
        )
        self.convout = nn.Sequential(
            nn.Conv2d(64, 64, (3, 3), 1, 1),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 3, (3, 3), 1, 1)
        )
        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def _makelayers(self, inchannel, outchannel, block_num, stride=1):
        layers = []
        for i in range(0, block_num):
            layers.append(_ResBLockDB(inchannel, outchannel))
        return nn.Sequential(*layers)

    def forward(self, x):
        con1 = self.relu(self.conv1(x))
        res1 = self.resBlock1(con1)
        res1 = torch.add(res1, con1)
        con2 = self.conv2(res1)
        res2 = self.resBlock2(con2)
        res2 = torch.add(res2, con2)
        con3 = self.conv3(res2)
        res3 = self.resBlock3(con3)
        res3 = torch.add(res3, con3)
        decon1 = self.deconv1(res3)
        deblur_feature = self.deconv2(decon1)
        deblur_out = self.convout(torch.add(deblur_feature, con1))
        return deblur_feature, deblur_out


class _SRMoudle(nn.Module):
    def __init__(self, block_num=8, in_channel=3):
        super(_SRMoudle, self).__init__()
        self.conv1 = nn.Conv2d(in_channel, 64, (7, 7), 1, padding=3)
        self.relu = nn.LeakyReLU(0.2, inplace=True)
        self.resBlock = self._makelayers(64, 64, block_num, 1)
        self.conv2 = nn.Conv2d(64, 64, (3, 3), 1, 1)

        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def _makelayers(self, inchannel, outchannel, block_num, stride=1):
        layers = []
        for i in range(0, block_num):
            layers.append(_ResBlockSR(inchannel, outchannel))
        return nn.Sequential(*layers)

    def forward(self, x):
        con1 = self.relu(self.conv1(x))
        res1 = self.resBlock(con1)
        con2 = self.conv2(res1)
        sr_feature = torch.add(con2, con1)
        return sr_feature


class _GateMoudle(nn.Module):
    def __init__(self):
        super(_GateMoudle, self).__init__()

        self.conv1 = nn.Conv2d(131, 64, (3, 3), 1, 1)
        self.relu = nn.LeakyReLU(0.2, inplace=True)
        self.conv2 = nn.Conv2d(64, 64, (1, 1), 1, padding=0)

        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def forward(self, x):
        con1 = self.relu(self.conv1(x))
        scoremap = self.conv2(con1)
        return scoremap


class _ReconstructMoudle(nn.Module):
    def __init__(self):
        super(_ReconstructMoudle, self).__init__()
        self.resBlock = self._makelayers(64, 64, 8)
        self.conv1 = nn.Conv2d(64, 256, (3, 3), 1, 1)
        self.pixelShuffle1 = nn.PixelShuffle(2)
        self.relu1 = nn.LeakyReLU(0.1, inplace=True)
        self.conv2 = nn.Conv2d(64, 256, (3, 3), 1, 1)
        self.pixelShuffle2 = nn.PixelShuffle(2)
        self.relu2 = nn.LeakyReLU(0.2, inplace=True)
        self.conv3 = nn.Conv2d(64, 64, (3, 3), 1, 1)
        self.relu3 = nn.LeakyReLU(0.2, inplace=True)
        self.conv4 = nn.Conv2d(64, 3, (3, 3), 1, 1)

        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def _makelayers(self, inchannel, outchannel, block_num, stride=1):
        layers = []
        for i in range(0, block_num):
            layers.append(_ResBLockDB(inchannel, outchannel))
        return nn.Sequential(*layers)

    def forward(self, x):
        res1 = self.resBlock(x)
        con1 = self.conv1(res1)
        pixelshuffle1 = self.relu1(self.pixelShuffle1(con1))
        con2 = self.conv2(pixelshuffle1)
        pixelshuffle2 = self.relu2(self.pixelShuffle2(con2))
        con3 = self.relu3(self.conv3(pixelshuffle2))
        sr_deblur = self.conv4(con3)
        return sr_deblur


class Net(nn.Module):
    def __init__(self, rgb_range):
        super(Net, self).__init__()
        self.deblurMoudle = self._make_net(_DeblurringMoudle)
        self.srMoudle_first = _SRMoudle(block_num=6, in_channel=3)
        self.srMoudle_second = _SRMoudle(block_num=6, in_channel=64)
        self.denoiseMoudle = RIDNET(rgb_range=rgb_range, block_num=4)
        self.gateMoudle_first = self._make_net(_GateMoudle)
        self.gateMoudle_second = self._make_net(_GateMoudle)
        self.reconstructMoudle = self._make_net(_ReconstructMoudle)

    def forward(self, x, gated, isTest):
        if isTest == True:
            origin_size = x.size()
            input_size = (math.ceil(origin_size[2] / 4) * 4, math.ceil(origin_size[3] / 4) * 4)
            out_size = (origin_size[2] * 4, origin_size[3] * 4)
            x = nn.functional.upsample(x, size=input_size, mode='bilinear')

        deblur_feature, deblur_out = self.deblurMoudle(x)
        denoise_feature, denoise_out = self.denoiseMoudle(x)
        sr_feature = self.srMoudle_first(x)
        if gated == True:
            scoremap1 = self.gateMoudle_first(torch.cat((denoise_feature, x, sr_feature), 1))
            repair_feature = torch.mul(scoremap1, denoise_feature)
            fusion_feature1 = torch.add(sr_feature, repair_feature)
            scoremap2 = self.gateMoudle_first(torch.cat((denoise_feature, x, fusion_feature1), 1))
            repair_feature = torch.mul(scoremap2, denoise_feature)
            fusion_feature2 = torch.add(fusion_feature1, repair_feature)
            scoremap3 = self.gateMoudle_first(torch.cat((denoise_feature, x, fusion_feature2), 1))
            repair_feature = torch.mul(scoremap3, denoise_feature)
            fusion_feature = self.srMoudle_second(torch.add(fusion_feature2, repair_feature))

            scoremap1 = self.gateMoudle_second(torch.cat((deblur_feature, x, fusion_feature), 1))
            repair_feature = torch.mul(scoremap1, deblur_feature)
            fusion_feature1 = torch.add(fusion_feature, repair_feature)
            scoremap2 = self.gateMoudle_second(torch.cat((deblur_feature, x, fusion_feature1), 1))
            repair_feature = torch.mul(scoremap2, deblur_feature)
            fusion_feature2 = torch.add(fusion_feature1, repair_feature)
            scoremap3 = self.gateMoudle_second(torch.cat((deblur_feature, x, fusion_feature2), 1))
            repair_feature = torch.mul(scoremap3, deblur_feature)
            fusion_feature = torch.add(fusion_feature2, repair_feature)

        else:
            fusion_feature = sr_feature + denoise_feature + deblur_feature

        recon_out = self.reconstructMoudle(fusion_feature)

        if isTest == True:
            recon_out = nn.functional.upsample(recon_out, size=out_size, mode='bilinear')

        return denoise_out, deblur_out, recon_out

    def _make_net(self, net):
        nets = []
        nets.append(net())
        return nn.Sequential(*nets)


class Edge_loss(nn.Module):
    """L1 Charbonnierloss."""

    def __init__(self):
        super(Edge_loss, self).__init__()
        self.conv_edge = nn.Conv2d(in_channels=3, out_channels=3, kernel_size=15, stride=1, padding=7, bias=False)
        for i in self.modules():
            if isinstance(i, nn.Conv2d):
                j = i.kernel_size[0] * i.kernel_size[1] * i.out_channels
                i.weight.data.normal_(0, math.sqrt(2 / j))
                if i.bias is not None:
                    i.bias.data.zero_()

    def forward(self, X, Y):
        diff = torch.add(X, -Y)
        error = torch.sqrt(diff * diff + self.eps)
        loss = torch.sum(error)
        return loss
