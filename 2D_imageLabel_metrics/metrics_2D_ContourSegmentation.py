#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''

This is just a scratch code that will be used for assessing 2D contours for task-I of P2ILF challenge 

I/P: Predicted images in RGB with R (ridge): (255,0,0); B (ligament): (0,0, 255) and Yellow (Silhouette): (255,255,0) - Make sure that this in this format (you can check with ImageJ)
--> Please note we have used opencv function to read which reads images as BGR and this has been handled in the code

O/P: we will use this to take the mean of precision and distance computed in this example for 2D mask predictions 

'''

import os
import numpy as np
import torch
from skimage import morphology
from scipy import ndimage
import sys


print("Python version")
print (sys.version)
print("Version info.")
print (sys.version_info)

def IoU(tp,fp,tn,fn):
    if tp +fp + fn == 0:
        return 0
    return tp / (tp+fp+fn)

def IoUClass(confusion_matrix, id_class):
    tp, fp, tn, fn = confusionMatrixClass(confusion_matrix, id_class)
    return IoU(tp, fp, tn, fn)

def sensitivity(tp,fp,tn,fn):
    if tp+fn == 0:
        return 0
    return tp / (tp+fn)

def sensitivityClass(confusion_matrix, id_class):
    tp, fp, tn, fn = confusionMatrixClass(confusion_matrix, id_class)
    return sensitivity(tp, fp, tn, fn)

def precision(tp,fp,tn,fn):
    if tp + fp == 0:
        return 0
    return tp / (tp+fp)

def precisionClass(confusion_matrix, id_class):
    tp, fp, tn, fn = confusionMatrixClass(confusion_matrix, id_class)
    return precision(tp, fp, tn, fn)


# Distance transform
def computeTDT(contour_image, threshold=None,norm=True):
    """
    contour:[h,w] with values in {0,1} 1 means contours
    return tdt in [0,1]
    """
    if threshold is None:
        threshold = 255
    # if contour contain no contour pixel
    if np.sum(contour_image) == 0:
        return threshold * np.ones_like(contour_image,dtype=np.float64)

    # requires contour to value 0
    inversedContour = 1 - contour_image
    dt = ndimage.distance_transform_edt(inversedContour)
    dt = np.float32(dt)


    #apply threshold
    dt[dt > threshold] = threshold
    if norm:
        dt = dt  / threshold
    return dt

def distContour2Dt(contour, dt):
    assert contour.shape == dt.shape

    dist = contour.to(torch.float64) * dt.to(torch.float64)
    return dist

def symDist2(P,G, P_dt=None, G_dt=None, threshold_dt=50, reduction=False, norm='gt'):
    if P_dt is None:
        P_dt = torch.from_numpy(computeTDT(P.numpy(), threshold_dt,norm=False))
    if G_dt is None:
        G_dt = torch.from_numpy(computeTDT(G.numpy(), threshold_dt,norm=False))

    dPG = distContour2Dt(P, G_dt)
    dGP = distContour2Dt(G, P_dt)
    # Normalization by
    if norm == 'gt':
        N = 1 if G.sum() == 0 else G.sum().item()
    elif norm == 'both':
        N = 1 if G.sum() + P.sum() == 0 else (P.sum() + G.sum()).item()
    elif norm == 'respective':
        # norm according to respective number of elemnts in
        norm_G = 1 if G.sum() == 0 else G.sum().item()
        norm_P = 1 if G.sum() == 0 else P.sum().item()
        distSym = dPG / P + dGP / G
        if reduction:
            return torch.sum(distSym).item()
        return distSym
    elif norm == 'none':
        N=2

    # for gt and both norm cases:
    distSym = (dPG + dGP) / N
    if reduction:
        return torch.sum(distSym).item()
    return distSym


def thinPrediction(contour_input, n_class, area_threshold_hole=5, min_size_elements=5):
    """
    Thin prediction contour:
    Input should be torch Tensor
    """
    if isinstance(contour_input, torch.Tensor):
        contour_input = contour_input.numpy()
    # work on copy
    contour = contour_input.copy()

    if n_class > 1:
        for i in range(1,n_class):

            mask = contour == i
            c = morphology.remove_small_holes(mask, area_threshold=area_threshold_hole)
            c = morphology.remove_small_objects(c, min_size=min_size_elements)
            thin_mask = morphology.skeletonize(c)
            # erase
            contour[mask] = 0
            # draw skeleton
            contour[thin_mask] = i
        return torch.from_numpy(contour)
    

def confusionMatrix(input,target, n_class):
    """
    Compute confusion matrix for tensor torch
    https://en.wikipedia.org/wiki/Confusion_matrix

    input: [H, W]
    target: [H,W]

    return confusion_matrix[n_class, n_class]
    predicted_class 0-axis,
    actual class 1-axis
    """
    # assert input.dim() == 2, "Input is not 2 dim tensor"
    # assert target.dim() == 2,"Target is not 2 dim tensor"
    matrix = torch.zeros((n_class, n_class))

    for i_true in range(n_class):
        target_i = target == i_true
        for j_predict in range(n_class):
            # extract predicted class j
            input_j = input == j_predict

            S = torch.sum(target_i[input_j])
            matrix[j_predict,i_true] = S.item()

    return matrix

def confusionMatrixClass(confusion_matrix, id_class):
    """
    From confusion matrix, return associated postive and negative confusion
    retuns: true_pos, false_pos, true_neg, false_neg
    """
    # actual class that is predicted class (cm[id,id] element)
    true_positive = confusion_matrix[id_class, id_class]
    # actual class - true positive
    false_positive = torch.sum(confusion_matrix[id_class, :]) - true_positive
    # predicted class - true positive
    false_negative = torch.sum(confusion_matrix[:, id_class]) - true_positive
    # rest of confusion matrix
    true_negative = torch.sum(confusion_matrix[:]) - true_positive - false_negative - false_positive

    return true_positive.item(), false_positive.item(), true_negative.item(), false_negative.item()


def computeClassificationMetrics(input, target, n_class, list_metrics,skip_class0=True):
    # compute confusion matrix:
    confusion_matrix = confusionMatrix(input, target, n_class)
    l_confusion=[]
    for i in range(n_class):
        if skip_class0 and i == 0:
            continue
        l_confusion.append(confusionMatrixClass(confusion_matrix, i))

    metrics = torch.zeros((len(l_confusion), len(list_metrics)),dtype=torch.float64)
    for i,confusion in enumerate(l_confusion):
        for j,f in enumerate(list_metrics):
            m = f(*confusion)
            metrics[i,j] = m
    return metrics    

def convertToOneHot(T, n_class):
    """
    T is [B,H,W]
    one_hot is [B,C,H,W]
    """
    if T.dim() == 3:
        T_one_hot = torch.nn.functional.one_hot(T.long(), n_class) # new_shape = shape+[n_class]
        target = T_one_hot.permute(0,3,1,2) # [B, N, H, W]

    elif T.dim() == 2:
        T_one_hot = torch.nn.functional.one_hot(T.long(),n_class)
        target = T_one_hot.permute(2,0,1) # [N, H, W]
    return target

def get_args():
    import argparse
    parser = argparse.ArgumentParser(description="segmentation metrics - 2D", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--GTImage", type=str, default="image_labels_GT/P2ILF22_patient1_12_GT.jpg", help="supply a GT '.jpg' image")
    parser.add_argument("--EvalImage", type=str, default="image_labels_eval/P2ILF22_patient1_12_eval_removed_2.jpg", help="P2ILF22_patient1_12_eval_removed.jpg, P2ILF22_patient1_12_eval_eroded.jpg")
    args = parser.parse_args()
    return args

def convertGT_toOneHotEncoding(GTimage, nclass): 
    GTimage[GTimage[:,:,:] > 230] = 255
    GTimage[GTimage[:,:,:] <= 230] = 0
    
    GTimageTest=np.zeros(GTimage.shape)
    GTimageTestCollapse=np.zeros((GTimage.shape[0],GTimage.shape[1]))
    # Ligament (B G R)
    #  BGR: convert to background: 0 (0,0,0); class silhouette: 1 (0, 255,255); class ridges: 2 (0,255,0) and class ligament: 3 (0,0,255)
    GTimageTest[:,:,0] = GTimage[:,:,0]
    GTimageTest[:,:,1] = GTimage[:,:,1]
    GTimageTest[:,:,2] = GTimage[:,:,2]-GTimage[:,:,1]
    
    # GTimageTest[GTimageTest[:,:,2]<=200] = 0
    GTimageTest[:,:,2][GTimageTest[:,:,2]==255] = 1 # Ridge
    GTimageTest[:,:,0][GTimageTest[:,:,0]==255] = 2 # Ligament
    GTimageTest[:,:,1][GTimageTest[:,:,1]==255] = 3 # Silhouette

    
    # GTimageTestCollapse = GTimageTest[:,:,0] + GTimageTest[:,:,1] + GTimageTest[:,:,2]
    idx = np.where(GTimageTest[:,:,2]==1)
    GTimageTestCollapse[idx] = 1
    idx = np.where(GTimageTest[:,:,0]==2)
    GTimageTestCollapse[idx] = 2
    idx = np.where(GTimageTest[:,:,1]==3)
    GTimageTestCollapse[idx] = 3
        
    GTimageTestCollapse = torch.tensor(GTimageTestCollapse.astype('uint8'))
    
    T_one_hot_GT = torch.nn.functional.one_hot(GTimageTestCollapse.type(torch.int64), nclass)
    # target = T_one_hot_GT.permute(2,0,1) # [N, H, W]
    return T_one_hot_GT, GTimageTest
    

if __name__ == "__main__":
    
    import cv2
    import matplotlib.pyplot as plt

    basePath = './'
    nclass = 4
    
    args = get_args()
    GTimage = cv2.imread(os.path.join(basePath, args.GTImage))
    T_one_hot_GT, GTimageTest = convertGT_toOneHotEncoding(GTimage, nclass)
   
    evalimage = cv2.imread(os.path.join(basePath, args.EvalImage))
    T_one_hot_eval, evalimageTest = convertGT_toOneHotEncoding(evalimage, nclass)
    
    binary_edges = evalimageTest > 0
    
    # i/p: contour_input, n_class, area_threshold_hole=5, min_size_elements=5)
    b1 = thinPrediction(binary_edges[:,:,0], 3, 5, 5) # L
    b2 = thinPrediction(binary_edges[:,:,1], 3, 5, 5) # S
    b3 = thinPrediction(binary_edges[:,:,2], 3, 5, 5) # R
    

    gtErode = False
    if gtErode:
        gt1 = thinPrediction(GTimageTest[:,:,0]>0, 3, 1, 1) # L
        gt2 = thinPrediction(GTimageTest[:,:,1]>0, 3, 5, 5) # S
        gt3 = thinPrediction(GTimageTest[:,:,2]>0, 3, 5, 5) # R

    
    list_metrics = [precision, sensitivity]
    
    # i/p: computeClassificationMetrics(input, target, n_class, list_metrics,skip_class0=True):
    metrics_Ligament = computeClassificationMetrics(b1, T_one_hot_GT[:,:,2], nclass , list_metrics, skip_class0=True)
    print(metrics_Ligament[0])
    metrics_SL = computeClassificationMetrics(b2, T_one_hot_GT[:,:,3], nclass , list_metrics, skip_class0=True)
    print(metrics_SL[0])
    metrics_Ridge= computeClassificationMetrics(b3, T_one_hot_GT[:,:,1], nclass , list_metrics, skip_class0=True)
    print(metrics_Ridge[0])
    
    # metrics1 = computeClassificationMetrics(b1.type(torch.float32), torch.tensor(GTimageTest[:,:,0]).type(torch.float32), 4 , list_metrics, skip_class0=True)
    # print(metrics1)
    # metrics2 = computeClassificationMetrics(b2.type(torch.float32), torch.tensor(GTimageTest[:,:,1]).type(torch.float32), 4 , list_metrics, skip_class0=True)
    # print(metrics2)
    # metrics3 = computeClassificationMetrics(b3.type(torch.float32), torch.tensor(GTimageTest[:,:,2]).type(torch.float32), 4 , list_metrics, skip_class0=True)
    # print(metrics3)
    
    metricsdist_Ligament = symDist2((b1 > 0).type(torch.float32), T_one_hot_GT[:,:,2], reduction=True)
    print(metricsdist_Ligament)
    metricsdist_SL = symDist2((b2 > 0).type(torch.float32), T_one_hot_GT[:,:,3], reduction=True)
    print(metricsdist_SL)
    metricsdist_Ridge = symDist2((b3 > 0).type(torch.float32),T_one_hot_GT[:,:,1], reduction=True)
    print(metricsdist_Ridge)
    