// Golden-vector generator for the Step-2 numeric spike: drives the real C++
// TimeDelayKalmanFilter (autoware_kalman_filter) through the test_time_delay_kalman_filter.cpp
// input constants and dumps the full extended state/covariance at 17 significant digits.
// Output lines: case,kind,i,j,value
#include "autoware/kalman_filter/time_delay_kalman_filter.hpp"

#include <cstdio>

using autoware::kalman_filter::TimeDelayKalmanFilter;

namespace
{
constexpr int kDimX = 3;
constexpr int kMaxDelayStep = 5;
constexpr double kInitialCovariance = 0.1;
constexpr double kProcessNoise = 0.01;
constexpr double kMeasurementNoise = 0.001;
constexpr double kStateTransitionScale = 2.0;
constexpr double kObservationScale = 0.5;

void dump(const char * name, const TimeDelayKalmanFilter & kf)
{
  Eigen::MatrixXd x;
  Eigen::MatrixXd p;
  kf.getX(x);  // public base-class accessors expose the full extended state
  kf.getP(p);
  for (int i = 0; i < x.rows(); ++i) {
    std::printf("%s,x,%d,0,%.17g\n", name, i, x(i, 0));
  }
  for (int i = 0; i < p.rows(); ++i) {
    for (int j = 0; j < p.cols(); ++j) {
      std::printf("%s,P,%d,%d,%.17g\n", name, i, j, p(i, j));
    }
  }
}

TimeDelayKalmanFilter make_initialized()
{
  Eigen::MatrixXd x_t(kDimX, 1);
  x_t << 1.0, 2.0, 3.0;
  const Eigen::MatrixXd p_t = Eigen::MatrixXd::Identity(kDimX, kDimX) * kInitialCovariance;
  TimeDelayKalmanFilter kf;
  kf.init(x_t, p_t, kMaxDelayStep);
  return kf;
}
}  // namespace

int main()
{
  const Eigen::MatrixXd a = Eigen::MatrixXd::Identity(kDimX, kDimX) * kStateTransitionScale;
  const Eigen::MatrixXd q = Eigen::MatrixXd::Identity(kDimX, kDimX) * kProcessNoise;
  const Eigen::MatrixXd c = Eigen::MatrixXd::Identity(kDimX, kDimX) * kObservationScale;
  const Eigen::MatrixXd r = Eigen::MatrixXd::Identity(kDimX, kDimX) * kMeasurementNoise;

  Eigen::MatrixXd x_next(kDimX, 1);
  x_next << 2.0, 4.0, 6.0;

  {
    auto kf = make_initialized();
    dump("init", kf);
  }
  {
    auto kf = make_initialized();
    kf.predictWithDelay(x_next, a, q);
    dump("predict1", kf);
  }
  for (int delay : {0, 2, 4}) {
    auto kf = make_initialized();
    kf.predictWithDelay(x_next, a, q);
    Eigen::MatrixXd y(kDimX, 1);
    y << 1.05, 2.05, 3.05;
    kf.updateWithDelay(y, c, r, delay);
    char name[32];
    std::snprintf(name, sizeof(name), "update_d%d", delay);
    dump(name, kf);
  }
  {
    auto kf = make_initialized();
    for (int i = 0; i < 3; ++i) {
      Eigen::MatrixXd x_pred(kDimX, 1);
      x_pred << 2.0 * (i + 1), 4.0 * (i + 1), 6.0 * (i + 1);
      kf.predictWithDelay(x_pred, a, q);
    }
    Eigen::MatrixXd y(kDimX, 1);
    y << 1.0, 2.0, 3.0;
    kf.updateWithDelay(y, c, r, 2);
    dump("multi_predict_update", kf);
  }
  return 0;
}
