import tensorflow as tf

from model.segnet import SegNet
from util.loss_functions import adv_loss, adv_loss_v2


class ADDA(SegNet):

    def __init__(self, args):
        SegNet.__init__(self, args)

        self.src_image_path = 'train.txt'
        # self.src_val_path = 'val.txt'
        self.tar_image_path = 'validation400.txt'
        # self.tar_val_path = 'rotate_180_val.txt'
        self.ckpt_path = args.transfer
        self.scope_s = 's'  # source scope
        self.scope_t = 't'  # target scope
        self.scope_d = 'd'  # discriminator scope
        self.scope_g = 'g'  # generator scope
        self.lr_g = 1e-3
        self.lr_d = 1e-3


    def discriminator(self, inputs, reuse=False, trainable=True):
        flat = tf.layers.Flatten()(inputs)
        with tf.variable_scope(self.scope_d, reuse=reuse):
            fc1 = tf.layers.dense(flat, 576, activation=tf.nn.leaky_relu, trainable=trainable, name='fc1')
            fc2 = tf.layers.dense(fc1, 576, activation=tf.nn.leaky_relu, trainable=trainable, name='fc2')
            fc3 = tf.layers.dense(fc2, 1, activation=None, trainable=trainable, name='fc3')
        return tf.nn.sigmoid(fc3)


    def train(self):
        image_h = self.image_h
        image_w = self.image_w
        image_c = self.image_c
        batch_size = self.batch_size

        src_x_train, src_y_train = self.dataset.batch(batch_size=batch_size, path=self.src_image_path)
        tar_x_train, tar_y_train = self.dataset.batch(batch_size=batch_size, path=self.tar_image_path)

        # for source domain
        # imitate inference, for restoring SegNet model
        src_encode_output = self.encoder(src_x_train, tf.constant(False))
        src_decode_output = self.decoder(src_encode_output, batch_size, tf.constant(False))
        logit_src, cls_loss_src = self.classifier(src_decode_output, src_y_train, self.loss_func)

        # variables to restore
        variable_averages = tf.train.ExponentialMovingAverage(self.moving_average_decay)
        src_variables = variable_averages.variables_to_restore()

        dis_src = self.discriminator(src_encode_output, reuse=False)
        dis_src = tf.Print(dis_src, [dis_src], summarize=batch_size, message="D_s: ")

        # for target domain
        with tf.variable_scope(self.scope_t):
            tar_encode_output = self.encoder(tar_x_train, phase_train=tf.constant(True))
        dis_tar = self.discriminator(tar_encode_output, reuse=True)
        dis_tar = tf.Print(dis_tar, [dis_tar], summarize=batch_size, message="D_t: ")

        # build loss
        g_loss, d_loss = adv_loss_v2(dis_src, dis_tar)

        # create optimizer for two task
        var_tar = tf.trainable_variables(self.scope_t)
        optim_g = tf.train.AdamOptimizer(self.lr_g).minimize(g_loss, var_list=var_tar)

        var_d = tf.trainable_variables(self.scope_d)
        optim_d = tf.train.AdamOptimizer(self.lr_d).minimize(d_loss, var_list=var_d)

        config = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)
        config.gpu_options.allow_growth = True

        with tf.Session(config=config) as sess:
            sess.run(tf.global_variables_initializer())
            src_saver = tf.train.Saver(src_variables)
            src_saver.restore(sess, self.ckpt_path)

            print("model restored successfully!")
            filewriter = tf.summary.FileWriter(logdir=self.log_dir, graph=sess.graph)

            for i in range(self.max_steps):
                _, d_loss_, = sess.run([optim_d, d_loss])
                _, g_loss_ = sess.run([optim_g, g_loss])
                if i % 10 == 0:
                    self.output.write("step:{}, g_loss:{:.4f}, d_loss:{:.4f}".format(i, g_loss_, d_loss_))
