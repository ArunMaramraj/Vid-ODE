import torch
import torch.nn as nn
import torch.optim as optim

class ConvNormAct(nn.Module):
    
    def __init__(self, in_ch, out_ch, kernel_size, stride, padding, act_type='lrelu'):
        
        super(ConvNormAct, self).__init__()
        
        layers = []
        layers.append(nn.Conv2d(in_ch, out_ch, kernel_size, stride, padding))
        
        layers.append(nn.InstanceNorm2d(out_ch))
        
        if act_type == 'relu':
            layers.append(nn.ReLU(inplace=False))
        elif act_type == 'lrelu':
            layers.append(nn.LeakyReLU(0.2,inplace=False))
        
        self.main = nn.Sequential(*layers)
    
    def forward(self, x):
        return self.main(x)


class Discriminator(nn.Module):
    
    def __init__(self, in_ch, device, seq=False, is_extrap=True):
        
        super(Discriminator, self).__init__()
        
        self.device = device
        self.seq = seq
        self.is_extrap = is_extrap
        
        self.layer_1 = nn.Sequential(
            nn.Conv2d(in_ch, 64, kernel_size=4, stride=2, padding=1, bias=False),
            nn.LeakyReLU(0.2, inplace = False))
        self.layer_2 = ConvNormAct(64, 128, kernel_size=4, stride=2, padding=1, act_type='lrelu')
        self.layer_3 = ConvNormAct(128, 256, kernel_size=4, stride=2, padding=1, act_type='lrelu')
        self.layer_4 = ConvNormAct(256, 512, kernel_size=4, stride=1, padding=2, act_type='lrelu')
        self.last_conv = nn.Conv2d(512, 64, kernel_size=4, stride=1, padding=2, bias=False)
    
    def forward(self, x):
        h1 = self.layer_1(x.clone())
        h2 = self.layer_2(h1.clone())
        h3 = self.layer_3(h2.clone())
        h4 = self.layer_4(h3.clone())
        return self.last_conv(h4.clone())
    
    def netD_adv_loss(self, real, fake, input_real):
        
        if self.seq:
            if self.is_extrap:
                real, fake = self.rearrange_seq(real.clone(), fake.clone(), input_real.clone(), only_fake=False)
            else:
                real, fake = self.rearrange_seq_interp(real.clone(), fake.clone(), input_real.clone(), only_fake=False)
        elif not self.seq:
            b, t, c, h, w = fake.size()
            real = real.contiguous().view(-1, c, h, w).clone()  # Clone after reshaping
            fake = fake.contiguous().view(-1, c, h, w).clone()  # Clone after reshaping
        
        pred_fake = self.forward(fake.detach().clone())  # Clone the detached fake data before forward pass
        pred_real = self.forward(real.clone())  # Clone real data before forward pass
        
        # GAN loss type
        real_label = torch.ones_like(pred_real).to(self.device)
        loss_fake = torch.mean((pred_fake) ** 2)
        loss_real = torch.mean((pred_real - real_label.clone()) ** 2)  # Clone the real label to ensure it's not modified in-place
        loss_D = (loss_real + loss_fake) * 0.5
    
        return loss_D
    
    def netG_adv_loss(self, fake, input_real):
        b, t, c, h, w = fake.size()
        if self.seq:
            if self.is_extrap:
                fake = self.rearrange_seq(None, fake.clone(), input_real.clone(), only_fake=True)
            else:
                fake = self.rearrange_seq_interp(None, fake.clone(), input_real.clone(), only_fake=True)
        elif not self.seq:
            fake = fake.contiguous().view(-1, c, h, w).clone()  # Clone fake after reshaping
        
        pred_fake = self.forward(fake.clone())  # Clone fake data before passing to forward
    
        # GAN loss type
        real_label = torch.ones_like(pred_fake).to(self.device).clone()  # Clone real label tensor
        loss_real = torch.mean((pred_fake - real_label) ** 2)
        
        return loss_real

     
    def rearrange_seq(self, real, fake, input_real, only_fake=True):
        
        b, t, c, h, w = fake.size()
        fake_seqs = []
        for i in range(t):
            # Clone before concatenating to avoid any in-place operations
            fake_seq = torch.cat([input_real[:, i:, ...].clone(), fake[:, :i+1, ...].clone()], dim=1)
            fake_seqs = fake_seqs + [fake_seq]
        fake_seqs = torch.cat(fake_seqs, dim=0).view(b * t, -1, h, w).clone()  # Clone after concatenation
    
        if only_fake:
            return fake_seqs
    
        real_seqs = []
        for i in range(t):
            # Clone before concatenating to avoid in-place operations
            real_seq = torch.cat([input_real[:, i:, ...].clone(), real[:, :i+1, ...].clone()], dim=1)
            real_seqs  = real_seqs + [real_seq]
        real_seqs = torch.cat(real_seqs, dim=0).view(b * t, -1, h, w).clone()  # Clone after concatenation
    
        return real_seqs, fake_seqs
    
    
    def rearrange_seq_interp(self, real, fake, input_real, only_fake=True):
    
        b, t, c, h, w = fake.size()
        mask = torch.eye(t).float().cuda().clone()  # Clone mask to avoid in-place changes
        fake_seqs = []
        for i in range(t):
            reshaped_mask = mask[i].view(1, -1, 1, 1, 1).clone()  # Clone reshaped_mask
            fake_seq = ((1 - reshaped_mask) * input_real.clone()) + (reshaped_mask * fake.clone())  # Clone input_real and fake
            fake_seqs = fake_seqs + [fake_seq]
        fake_seqs = torch.cat(fake_seqs, dim=0).view(b * t, -1, h, w).clone()  # Clone after concatenation
    
        if only_fake:
            return fake_seqs
    
        real_seqs = []
        for i in range(t):
            reshaped_mask = mask[i].view(1, -1, 1, 1, 1).clone()  # Clone reshaped_mask
            real_seq = ((1 - reshaped_mask) * input_real.clone()) + (reshaped_mask * real.clone())  # Clone input_real and real
            real_seqs = real_seqs + [real_seq]
        real_seqs = torch.cat(real_seqs, dim=0).view(b * t, -1, h, w).clone()  # Clone after concatenation
    
        return real_seqs, fake_seqs



def create_netD(opt, device):
    
    # Model
    seq_len = opt.sample_size // 2
    if opt.irregular and not opt.extrap:
        seq_len = opt.sample_size
    
    if opt.extrap:
        seq_len = seq_len + 1

    netD_img = Discriminator(in_ch=3, device=device, seq=False, is_extrap=opt.extrap).to(device)
    netD_seq = Discriminator(in_ch=3 * (seq_len), device=device, seq=True, is_extrap=opt.extrap).to(device)

    # Optimizer
    optimizer_netD = optim.Adamax(list(netD_img.parameters()) + list(netD_seq.parameters()), lr=opt.lr)
    
    return netD_img, netD_seq, optimizer_netD
