import time
import math
import mxnet as mx
import numpy as np
from scipy import stats

from almond import LatentModel, VAEEncoder, VAEDecoder, ConditionalNormal

class Logger:
    def __init__(self, filename=None):
        self.filename = filename
        if filename is not None:
            with open(filename, "w") as f:
                f.write("")

    def log(self, str):
        if self.filename is not None:
            with open(self.filename, "a") as f:
                f.write(str)
                f.write("\n")
        else:
            print(str)


# Number of GPUs for computation
num_gpus = 1
ctx = [mx.gpu(i) for i in range(num_gpus)]
# Otherwise, use CPU
# ctx = [mx.cpu()]

# Logger
# logger = Logger("mnn_mix_simulation.log")
logger = Logger()

# Generate data
def gen_mu_mixture_prior(n, mu1=0.0, mu2=3.0, p1=0.3, sigma=1.0):
    mean = np.zeros(n) + mu2
    ind = np.random.binomial(1, p1, n).astype(bool)
    mean[ind] = mu1
    mu = np.random.normal(loc=mean, scale=sigma)
    x = mu + np.random.randn(n)
    return mu, x


# Parameters
np.random.seed(123)
mx.random.seed(123)
n = 1000            # sample size
mix_par = {"mu1": 0.0, "mu2": 3.0, "p1": 0.4, "sigma": 0.5}  # prior distribution parameters
nsim = 100          # number of simulation runs

batch_size = n      # batch size in model fitting
nchain = 100        # number of Langevin chains
est_nsamp = 5000    # sample size of estimated prior

mu0_dat = np.zeros(shape=(nsim, est_nsamp))
mu_est_vae_dat = np.zeros(shape=(nsim, est_nsamp))
mu_est_bc_dat = np.zeros(shape=(nsim, est_nsamp))
mu_est_eb_dat = np.zeros(shape=(nsim, est_nsamp))

norm1 = stats.norm(loc=mix_par["mu1"], scale=mix_par["sigma"])
norm2 = stats.norm(loc=mix_par["mu2"], scale=mix_par["sigma"])
def true_dist(x):
    return mix_par["p1"] * norm1.cdf(x) + (1.0 - mix_par["p1"]) * norm2.cdf(x)

for i in range(nsim):
    logger.log("===> Simulation {}\n".format(i))

    t1 = time.time()
    mu0, _ = gen_mu_mixture_prior(est_nsamp, **mix_par)

    # Data
    mu, x = gen_mu_mixture_prior(n, **mix_par)
    xt = mx.nd.array(x).reshape(-1, 1)

    # Empirical Bayes estimation
    eb_mu = np.mean(x)
    eb_var = np.var(x) - 1.0
    mu_est_eb = np.random.normal(eb_mu, math.sqrt(eb_var), est_nsamp)

    # Model
    model = LatentModel(ConditionalNormal(dimu=1),
                        encoder=VAEEncoder([1, 50, 100, 50], latent_dim=1),
                        decoder=VAEDecoder([50, 100, 50, 1], latent_dim=1, npar=1),
                        sim_z=100, nchain=nchain, ctx=ctx)
    model.init(lr=0.01, lr_bc=0.01)

    # Model fitting
    logger.log("     => VAE")

    model.fit(xt, epochs=1000, batch_size=batch_size, eval_nll=False, verbose=False)
    mu_est_vae = model.simulate_prior(est_nsamp)[0].squeeze()
    ks = stats.kstest(mu_est_vae, true_dist)
    w = stats.wasserstein_distance(mu0, mu_est_vae)

    logger.log("        => KS = {}, p-val = {}".format(ks.statistic, ks.pvalue))
    logger.log("        => W = {}\n".format(w))

    logger.log("     => Bias correction")

    particles = model.fit_bc(xt, epochs=1000, warmups=100, batch_size=batch_size,
                             burnin=10, step_size=0.01, eval_nll=False, verbose=False)
    mu_est_bc = model.simulate_prior(est_nsamp)[0].squeeze()
    ks = stats.kstest(mu_est_bc, true_dist)
    w = stats.wasserstein_distance(mu0, mu_est_bc)

    logger.log("        => KS = {}, p-val = {}".format(ks.statistic, ks.pvalue))
    logger.log("        => W = {}\n".format(w))

    mu0_dat[i, :] = mu0
    mu_est_vae_dat[i, :] = mu_est_vae
    mu_est_bc_dat[i, :] = mu_est_bc
    mu_est_eb_dat[i, :] = mu_est_eb

    t2 = time.time()
    logger.log("===> Simulation {} finished in {} seconds\n".format(i, t2 - t1))

np.savez("../results/mnn_mix_simulation.npz",
         mu0_dat=mu0_dat,
         mu_est_vae_dat=mu_est_vae_dat,
         mu_est_bc_dat=mu_est_bc_dat,
         mu_est_eb_dat=mu_est_eb_dat)
