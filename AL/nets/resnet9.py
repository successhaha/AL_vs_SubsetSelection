import os
import torch
import torchvision
import tarfile
import torch.nn as nn
import numpy as np
import torch.nn.functional as F
from .nets_utils import EmbeddingRecorder

class Mish(nn.Module):
    def __init__(self):
        super(Mish, self).__init__()

    def forward(self, x):
        return x * torch.tanh(F.softplus(x))


def accuracy(outputs, labels):
    _, preds = torch.max(outputs, dim=1)
    return torch.tensor(torch.sum(preds == labels).item() / len(preds))

class ImageClassificationBase(nn.Module):
    def training_step(self, batch):
        images, labels = batch 
        images = images.cuda()
        #labels = labels.cuda()
        out,_ = self(images)                  # Generate predictions        
        loss = F.cross_entropy(out, labels) # Calculate loss
        return loss
    
    def get_embedding(self, batch):
        images, labels = batch 
        images = images.cuda()
        #labels = labels.cuda()
        _,embbedding = self(images)                    # Generate predictions                
        return embbedding
    
    def validation_step(self, batch):
        images, labels = batch 
        images = images.cuda()
        #labels = labels.cuda()
        out,_ = self(images)                    # Generate predictions        
        loss = F.cross_entropy(out, labels)   # Calculate loss
        acc = accuracy(out, labels)           # Calculate accuracy
        return {'val_loss': loss.detach(), 'val_acc': acc}
        
    def validation_epoch_end(self, outputs):
        batch_losses = [x['val_loss'] for x in outputs]
        epoch_loss = torch.stack(batch_losses).mean()   # Combine losses
        batch_accs = [x['val_acc'] for x in outputs]
        epoch_acc = torch.stack(batch_accs).mean()      # Combine accuracies
        return {'val_loss': epoch_loss.item(), 'val_acc': epoch_acc.item()}
    
    def epoch_end(self, epoch, result):
        print("Epoch [{}], last_lr: {:.5f}, train_loss: {:.4f}, val_loss: {:.4f}, val_acc: {:.4f}".format(
            epoch, result['lrs'][-1], result['train_loss'], result['val_loss'], result['val_acc']))


def conv_block(in_channels, out_channels, pool=False, pool_no=2):
    layers = [nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1), 
              nn.BatchNorm2d(out_channels), 
              Mish()
              ]
    if pool: layers.append(nn.MaxPool2d(pool_no))
    return nn.Sequential(*layers)

class ResNet9(ImageClassificationBase):
    def __init__(self, in_channels, num_classes, im_size, record_embedding: bool = False, no_grad: bool = False,
                 pretrained: bool = False):
        super().__init__()
        
        if im_size[0] == 32 and im_size[1] == 32:
            self.conv1 = conv_block(in_channels, 64)
            self.conv2 = conv_block(64, 128, pool=True, pool_no=2) # 128, 16, 16
            self.res1 = nn.Sequential(conv_block(128, 128), conv_block(128, 128))
            
            self.conv3 = conv_block(128, 256, pool=True) # 256, 8, 8
            self.conv4 = conv_block(256, 256, pool=True, pool_no=2) # 256, 4, 4
            self.res2 = nn.Sequential(conv_block(256, 256), conv_block(256, 256))
            
            self.MP = nn.MaxPool2d(2) # 256, 2, 2
            self.FlatFeats = nn.Flatten()
            self.fc = nn.Linear(256,num_classes)

            self.embedding_recorder = EmbeddingRecorder(record_embedding)

        elif im_size[0] == 16 and im_size[1] == 16:
            self.conv1 = conv_block(in_channels, 64)
            self.conv2 = conv_block(64, 128, pool=True, pool_no=2) # 128, 8, 8
            self.res1 = nn.Sequential(conv_block(128, 128), conv_block(128, 128))
            
            self.conv3 = conv_block(128, 256)
            self.conv4 = conv_block(256, 256, pool=True, pool_no=2) # 256, 4, 4
            self.res2 = nn.Sequential(conv_block(256, 256), conv_block(256, 256))

            self.embedding_recorder = EmbeddingRecorder(record_embedding)
            
            self.fc = nn.Linear(256, num_classes)

        elif im_size[0] == 8 and im_size[1] == 8:
            self.conv1 = conv_block(in_channels, 64)
            self.conv2 = conv_block(64, 128, pool=True, pool_no=2) # 128, 4, 4
            self.res1 = nn.Sequential(conv_block(128, 128), conv_block(128, 128))
            
            self.conv3 = conv_block(128, 256)
            self.conv4 = conv_block(256, 256) # 256, 4, 4
            self.res2 = nn.Sequential(conv_block(256, 256), conv_block(256, 256))

            self.embedding_recorder = EmbeddingRecorder(record_embedding)
            
            self.fc = nn.Linear(256,num_classes)
        
    def forward(self, xb):
        out = self.conv1(xb)
        out = self.conv2(out)
        out = self.res1(out) + out
        out = self.conv3(out)
        out = self.conv4(out)        
        out = self.res2(out) + out    

        out = F.avg_pool2d(out, 4)
        out = out.view(out.size(0), -1)

        out_emb = self.embedding_recorder(out)

        #out = self.MP(out)
        #out_emb = self.FlatFeats(out)
        out = self.fc(out_emb)
        return out #, out_emb

    def get_last_layer(self):
        return self.fc