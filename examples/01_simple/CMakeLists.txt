cmake_minimum_required(VERSION 3.20)

project(nml_optimization_example LANGUAGES Fortran)

set(CMAKE_Fortran_STANDARD 2008)
set(CMAKE_Fortran_STANDARD_REQUIRED ON)

add_executable(nml_optimization_example
  main.f90
  out/nml_helper.f90
  out/nml_optimization.f90
)
