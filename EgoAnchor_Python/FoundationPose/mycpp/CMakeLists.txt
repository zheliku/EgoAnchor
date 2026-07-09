cmake_minimum_required(VERSION 3.15)
project(mycpp)

if(POLICY CMP0148)
  cmake_policy(SET CMP0148 NEW)
endif()

if(POLICY CMP0167)
  cmake_policy(SET CMP0167 OLD)
endif()

set(CMAKE_BUILD_TYPE Release)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
  add_compile_options(/O2 /utf-8)
else()
  add_compile_options(-O3 -g3)
endif()


find_package(Boost REQUIRED)
find_package(Eigen3 REQUIRED)
set(PYBIND11_FINDPYTHON ON)
if(NOT DEFINED Python_ROOT_DIR AND DEFINED ENV{CONDA_PREFIX})
  set(Python_ROOT_DIR "$ENV{CONDA_PREFIX}")
endif()
find_package(Python REQUIRED COMPONENTS Interpreter Development)
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION OFF)
find_package(pybind11 REQUIRED)

if(NOT CMAKE_CXX_COMPILE_FEATURES)
  set(CMAKE_CXX_COMPILE_FEATURES
    cxx_inheriting_constructors
    cxx_right_angle_brackets
    cxx_user_literals
  )
endif()

include_directories(
  include
  ${Boost_INCLUDE_DIRS}
  ${BLAS_INCLUDE_DIR}
)

file(GLOB MY_SRC ${PROJECT_SOURCE_DIR}/src/*.cpp)

pybind11_add_module(mycpp NO_EXTRAS src/app/pybind_api.cpp ${MY_SRC})
target_link_libraries(mycpp PRIVATE Eigen3::Eigen)
