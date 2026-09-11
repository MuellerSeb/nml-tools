cmake_minimum_required(VERSION 3.20)
project(generated_namespaces LANGUAGES Fortran)

set(CMAKE_Fortran_STANDARD 2008)
set(CMAKE_Fortran_STANDARD_REQUIRED ON)

add_executable(generated_namespaces
  conformance.f90
  out/nml_helper.f90
  out/nml_namespaces.f90
)
