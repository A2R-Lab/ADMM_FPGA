# src/quadrotor.py
import autograd.numpy as np
from autograd.numpy.linalg import norm
from autograd.numpy.linalg import inv
from autograd import jacobian
import math

class CrazyLoihiModel:
    def __init__(self, freq=50.0):
        # Quadrotor parameters
        self.mass = 0.048
        self.J = np.array([[2.3951e-5, 0.0, 0.0],
                          [0.0, 2.3951e-5, 0.0],
                          [0.0, 0.0, 3.2347e-5]])
        self.g = 9.81
        self.thrustToTorque = 0.002078
        self.el = 0.0353
        self.scale = 65535
        self.kt = 2.90e-6 * self.scale
        self.km = self.kt * self.thrustToTorque

        self.freq = freq
        self.dt = 1/freq  # matches h = 1/freq

        self.nx = 12
        self.nu = 4
        
        self.hover_thrust = (self.mass * self.g / self.kt / 4) * np.ones(4)
        print("Hover thrust (raw):", self.hover_thrust)
    
    def step(self, x, u):
        x_next = self.dynamics_rk4(np.hstack([x[0:3], self.rptoq(x[3:6]), x[6:13]]), u, self.dt)
        return np.hstack([x_next[0:3], self.qtorp(x_next[3:7]), x_next[7:13]])

    def dynamics(self, x, u, wind_vec=None):
        # Normalize quaternion at the start
        r = x[0:3]
        q = x[3:7]/norm(x[3:7])
        v = x[7:10]
        omg = x[10:13]
        Q = self.qtoQ(q)

        dr = v
        dq = 0.5 * self.L(q) @ self.H @ omg
        
        # Base acceleration
        dv = np.array([0, 0, -self.g]) + (1/self.mass) * Q @ np.array([[0, 0, 0, 0], 
                                                                       [0, 0, 0, 0], 
                                                                       [self.kt, self.kt, self.kt, self.kt]]) @ u
        
        # Add wind acceleration if provided
        if wind_vec is not None:
            dv += wind_vec
        
        domg = inv(self.J) @ (-self.hat(omg) @ self.J @ omg + 
                             np.array([[-self.el*self.kt, -self.el*self.kt, self.el*self.kt, self.el*self.kt], 
                                     [-self.el*self.kt, self.el*self.kt, self.el*self.kt, -self.el*self.kt], 
                                     [-self.km, self.km, -self.km, self.km]]) @ u)

        return np.hstack([dr, dq, dv, domg])

    def dynamics_rk4(self, x, u, dt=None, wind_vec=None):
        if dt is None:
            dt = self.dt
            
        # RK4 integration exactly as in reference
        f1 = self.dynamics(x, u, wind_vec)
        f2 = self.dynamics(x + 0.5*dt*f1, u, wind_vec)
        f3 = self.dynamics(x + 0.5*dt*f2, u, wind_vec)
        f4 = self.dynamics(x + dt*f3, u, wind_vec)
        
        xn = x + (dt/6.0)*(f1 + 2*f2 + 2*f3 + f4)
        xnormalized = xn[3:7]/norm(xn[3:7])
        
        return np.hstack([xn[0:3], xnormalized, xn[7:13]])
          

    def get_linearized_dynamics(self, x_ref, u_ref):
        """Get linearized dynamics matrices around reference point"""
        A_jac = jacobian(self.dynamics_rk4, 0)

        #print elements of A_jac 13 by 13 

        B_jac = jacobian(self.dynamics_rk4, 1)

        
        A = A_jac(x_ref, u_ref)
        B = B_jac(x_ref, u_ref)

        # print(A)
        # print(B)
        
        return self.E(x_ref[3:7]).T @ A @ self.E(x_ref[3:7]), self.E(x_ref[3:7]).T @ B

    @staticmethod
    def hat(v):
        return np.array([[0, -v[2], v[1]],
                        [v[2], 0, -v[0]],
                        [-v[1], v[0], 0]])

    @staticmethod
    def L(q):
        s = q[0]
        v = q[1:4]
        return np.vstack([
            np.hstack([s, -v]),
            np.hstack([v.reshape(3,1), s*np.eye(3) + CrazyLoihiModel.hat(v)])
        ])

    # Constants
    T = np.diag([1.0, -1, -1, -1])
    H = np.vstack([np.zeros((1,3)), np.eye(3)])

    @classmethod
    def qtoQ(cls, q):
        return cls.H.T @ cls.T @ cls.L(q) @ cls.T @ cls.L(q) @ cls.H

    @classmethod
    def G(cls, q):
        return cls.L(q) @ cls.H

    @staticmethod
    def rptoq(phi):
        return (1./math.sqrt(1 + phi.T @ phi)) * np.hstack([1, phi])

    @staticmethod
    def qtorp(q):
        return q[1:4]/q[0]

    @classmethod
    def E(cls, q):
        return np.vstack([
            np.hstack([np.eye(3), np.zeros((3,3)), np.zeros((3,6))]),
            np.hstack([np.zeros((4,3)), cls.G(q), np.zeros((4,6))]),
            np.hstack([np.zeros((6,3)), np.zeros((6,3)), np.eye(6)])
        ])

   