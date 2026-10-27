# MHM optimization namelist {#optimization}

[TOC]

All relevant configurations for the optimization parameters of MHM.
This namelist corresponds to the `optimization` section in the MHM configuration.

**Namelist**: `optimization`

## Fields

| Name | Type | Declared required | Input required | Info |
| --- | --- | --- | --- | --- |
| [name](#name) | string | no | no | Optimization name |
| [niterations](#niterations) | integer | yes | yes | Number of iterations |
| [tolerance](#tolerance) | real | yes | yes | Convergence tolerance |
| [seed](#seed) | integer | no | no | Random seed |
| [dds_r](#dds_r) | real | no | no | DDS perturbation rate |
| [mcmc_opti](#mcmc_opti) | logical | no | no | MCMC optimization |
| [mcmc_error_params](#mcmc_error_params) | real array | no | no | MCMC error parameters per domain |

## Field details

### name

Optimization name `name`

Name for the optimization run.

Summary:
- Type: `character(len=buf)`
- Declared required: no
- Input required: no
- Examples: `"test_optimization"`

### niterations

Number of iterations `niterations`

Number of iterations for the optimization algorithm

Summary:
- Type: `integer`
- Declared required: yes
- Input required: yes
- Examples: `100`

### tolerance

Convergence tolerance `tolerance`

Tolerance for convergence of the optimization algorithm.

Summary:
- Type: `real`
- Declared required: yes
- Input required: yes

### seed

Random seed `seed`

Random seed for reproducibility. Use -9 for random seed.

Summary:
- Type: `integer(i4)`
- Declared required: no
- Input required: no
- Default: `-9`

### dds_r

DDS perturbation rate `dds_r`

Parameter for the DDS algorithm controlling the perturbation rate.

Summary:
- Type: `real(dp)`
- Declared required: no
- Input required: no
- Default: `0.2`

### mcmc_opti

MCMC optimization `mcmc_opti`

Whether to perform MCMC optimization.

Summary:
- Type: `logical`
- Declared required: no
- Input required: no
- Default: `.true.`

### mcmc_error_params

MCMC error parameters per domain `mcmc_error_params`

Parameters for the MCMC error model: err = a + b+Q

Summary:
- Type: `real(dp), dimension(3, 2, max_iter)`
- Declared required: no
- Input required: no
- Default: `[0.01, 0.6, 0.2, 0.3]` (repeated, order: C)

## Example

```fortran
&optimization
  name = "test_optimization"
  niterations = 100
  tolerance = 0.0
  seed = -9
  dds_r = 0.2
  mcmc_opti = .true.
  mcmc_error_params(1,1,:) = 0.01, 0.6, 0.2, 0.3
/
```

