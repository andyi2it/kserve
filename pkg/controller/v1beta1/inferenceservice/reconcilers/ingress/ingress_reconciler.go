/*
Copyright 2021 The KServe Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package ingress

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/google/go-cmp/cmp"
	"github.com/pkg/errors"
	"google.golang.org/protobuf/testing/protocmp"
	istiov1beta1 "istio.io/api/networking/v1beta1"
	istioclientv1beta1 "istio.io/client-go/pkg/apis/networking/v1beta1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	apierr "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/validation"
	"k8s.io/client-go/kubernetes"
	"knative.dev/pkg/apis"
	duckv1 "knative.dev/pkg/apis/duck/v1"
	"knative.dev/pkg/kmp"
	"knative.dev/pkg/network"
	"knative.dev/pkg/system"
	knservingv1 "knative.dev/serving/pkg/apis/serving/v1"
	"knative.dev/serving/pkg/reconciler/route/config"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	"github.com/kserve/kserve/pkg/apis/serving/v1beta1"
	"github.com/kserve/kserve/pkg/constants"
	"github.com/kserve/kserve/pkg/utils"
)

var (
	log = logf.Log.WithName("IngressReconciler")
)

type IngressReconciler struct {
	// client is the client that is used to access the custom resources
	client client.Client
	// clientset is the client that allows us to talk to the k8s for core APIs
	clientset     kubernetes.Interface
	scheme        *runtime.Scheme
	ingressConfig *v1beta1.IngressConfig
	deployConfig  *v1beta1.DeployConfig
}

func NewIngressReconciler(client client.Client, clientset kubernetes.Interface, scheme *runtime.Scheme, ingressConfig *v1beta1.IngressConfig, deployConfig *v1beta1.DeployConfig) *IngressReconciler {
	return &IngressReconciler{
		client:        client,
		clientset:     clientset,
		scheme:        scheme,
		ingressConfig: ingressConfig,
		deployConfig:  deployConfig,
	}
}

func getServiceHost(isvc *v1beta1.InferenceService) string {
	if isvc.Status.Components == nil {
		return ""
	}
	// Derive the ingress service host from underlying service url
	if isvc.Spec.Transformer != nil {
		if transformerStatus, ok := isvc.Status.Components[v1beta1.TransformerComponent]; !ok {
			return ""
		} else if transformerStatus.URL == nil {
			return ""
		} else {
			if strings.Contains(transformerStatus.URL.Host, "-default") {
				return strings.Replace(transformerStatus.URL.Host, fmt.Sprintf("-%s-default", string(constants.Transformer)), "",
					1)
			} else {
				return strings.Replace(transformerStatus.URL.Host, fmt.Sprintf("-%s", string(constants.Transformer)), "",
					1)
			}
		}
	}

	if predictorStatus, ok := isvc.Status.Components[v1beta1.PredictorComponent]; !ok {
		return ""
	} else if predictorStatus.URL == nil {
		return ""
	} else {
		if strings.Contains(predictorStatus.URL.Host, "-default") {
			return strings.Replace(predictorStatus.URL.Host, fmt.Sprintf("-%s-default", string(constants.Predictor)), "",
				1)
		} else {
			return strings.Replace(predictorStatus.URL.Host, fmt.Sprintf("-%s", string(constants.Predictor)), "",
				1)
		}
	}
}

func getAdditionalHosts(domainList *[]string, serviceHost string, config *v1beta1.IngressConfig, additionalHosts *[]string) {
	// Include additional ingressDomain to the domains (both internal and external)
	subdomain := ""
	if domainList != nil && len(*domainList) != 0 {
		for _, domain := range *domainList {
			res, found := strings.CutSuffix(serviceHost, domain)
			if found {
				subdomain = res
				break
			}
		}
	}
	if len(subdomain) != 0 && config.AdditionalIngressDomains != nil && len(*config.AdditionalIngressDomains) > 0 {
		// len(subdomain) != 0 means we have found the subdomain.
		// If the list of the additionalIngressDomains is not empty, we will append the valid host created by the
		// additional ingress domain.
		// Deduplicate the domains in the additionalIngressDomains, making sure that the returned additionalHosts
		// do not have duplicate domains.
		deduplicateMap := map[string]bool{}
		for _, domain := range *config.AdditionalIngressDomains {
			// If the domain is redundant, go to the next element.
			if !deduplicateMap[domain] {
				host := fmt.Sprintf("%s%s", subdomain, domain)
				if err := validation.IsDNS1123Subdomain(host); len(err) > 0 {
					log.Error(fmt.Errorf("The domain name %s in the additionalIngressDomains is not valid", domain),
						"Failed to get the valid host name")
					continue
				}
				*additionalHosts = append(*additionalHosts, host)
				deduplicateMap[domain] = true
			}
		}
	}
}

func getServiceUrl(isvc *v1beta1.InferenceService, config *v1beta1.IngressConfig) string {
	url := getHostBasedServiceUrl(isvc, config)
	if url == "" {
		return ""
	}
	if config.PathTemplate == "" {
		return url
	} else {
		return getPathBasedServiceUrl(isvc, config)
	}
}

func getPathBasedServiceUrl(isvc *v1beta1.InferenceService, config *v1beta1.IngressConfig) string {
	path, err := GenerateUrlPath(isvc.Name, isvc.Namespace, config)
	if err != nil {
		log.Error(err, "Failed to generate URL path from pathTemplate")
		return ""
	}
	url := &apis.URL{}
	url.Scheme = config.UrlScheme
	url.Host = config.IngressDomain
	url.Path = path

	return url.String()
}

func getHostBasedServiceUrl(isvc *v1beta1.InferenceService, config *v1beta1.IngressConfig) string {
	urlScheme := config.UrlScheme
	disableIstioVirtualHost := config.DisableIstioVirtualHost
	if isvc.Status.Components == nil {
		return ""
	}
	// Derive the ingress url from underlying service url
	if isvc.Spec.Transformer != nil {
		if transformerStatus, ok := isvc.Status.Components[v1beta1.TransformerComponent]; !ok {
			return ""
		} else if transformerStatus.URL == nil {
			return ""
		} else {
			url := transformerStatus.URL
			url.Scheme = urlScheme
			urlString := url.String()
			if !disableIstioVirtualHost {
				if strings.Contains(urlString, "-default") {
					return strings.Replace(urlString, fmt.Sprintf("-%s-default", string(constants.Transformer)), "", 1)
				} else {
					return strings.Replace(urlString, fmt.Sprintf("-%s", string(constants.Transformer)), "", 1)
				}
			}
			return urlString
		}
	}

	if predictorStatus, ok := isvc.Status.Components[v1beta1.PredictorComponent]; !ok {
		return ""
	} else if predictorStatus.URL == nil {
		return ""
	} else {
		url := predictorStatus.URL
		url.Scheme = urlScheme
		urlString := url.String()
		if !disableIstioVirtualHost {
			if strings.Contains(urlString, "-default") {
				return strings.Replace(urlString, fmt.Sprintf("-%s-default", string(constants.Predictor)), "", 1)
			} else {
				return strings.Replace(urlString, fmt.Sprintf("-%s", string(constants.Predictor)), "", 1)
			}
		}
		return urlString
	}
}

func (r *IngressReconciler) reconcileExternalService(isvc *v1beta1.InferenceService, config *v1beta1.IngressConfig) error {
	desired := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      isvc.Name,
			Namespace: isvc.Namespace,
		},
		Spec: corev1.ServiceSpec{
			ExternalName:    config.LocalGatewayServiceName,
			Type:            corev1.ServiceTypeExternalName,
			SessionAffinity: corev1.ServiceAffinityNone,
		},
	}
	if err := controllerutil.SetControllerReference(isvc, desired, r.scheme); err != nil {
		return err
	}

	// Create service if does not exist
	existing := &corev1.Service{}
	err := r.client.Get(context.TODO(), types.NamespacedName{Name: desired.Name, Namespace: desired.Namespace}, existing)
	if err != nil {
		if apierr.IsNotFound(err) {
			log.Info("Creating external name service", "namespace", desired.Namespace, "name", desired.Name)
			err = r.client.Create(context.TODO(), desired)
		}
		return err
	}

	// Return if no differences to reconcile.
	if equality.Semantic.DeepEqual(desired, existing) {
		return nil
	}

	// Reconcile differences and update
	diff, err := kmp.SafeDiff(desired.Spec, existing.Spec)
	if err != nil {
		return errors.Wrapf(err, "failed to diff external name service")
	}
	log.Info("Reconciling external service diff (-desired, +observed):", "diff", diff)
	log.Info("Updating external service", "namespace", existing.Namespace, "name", existing.Name)
	existing.Spec = desired.Spec
	existing.ObjectMeta.Labels = desired.ObjectMeta.Labels
	existing.ObjectMeta.Annotations = desired.ObjectMeta.Annotations
	err = r.client.Update(context.TODO(), existing)
	if err != nil {
		return errors.Wrapf(err, "fails to update external name service")
	}

	return nil
}

func createHTTPRouteDestination(gatewayService string) *istiov1beta1.HTTPRouteDestination {
	httpRouteDestination := &istiov1beta1.HTTPRouteDestination{
		Destination: &istiov1beta1.Destination{
			Host: gatewayService,
			Port: &istiov1beta1.PortSelector{
				Number: constants.CommonDefaultHttpPort,
			},
		},
		Weight: 100,
	}
	return httpRouteDestination
}

func createHTTPMatchRequest(prefix, targetHost, internalHost string, additionalHosts *[]string, isInternal bool, config *v1beta1.IngressConfig) []*istiov1beta1.HTTPMatchRequest {
	var uri *istiov1beta1.StringMatch
	if prefix != "" {
		uri = &istiov1beta1.StringMatch{
			MatchType: &istiov1beta1.StringMatch_Regex{
				Regex: prefix,
			},
		}
	}
	matchRequests := []*istiov1beta1.HTTPMatchRequest{
		{
			Uri: uri,
			Authority: &istiov1beta1.StringMatch{
				MatchType: &istiov1beta1.StringMatch_Regex{
					Regex: constants.HostRegExp(internalHost),
				},
			},
			Gateways: []string{config.LocalGateway, constants.IstioMeshGateway},
		},
	}
	if !isInternal {
		// We only create the HTTPMatchRequest for the targetHost and the additional hosts, when the ingress is not internal.
		matchRequests = append(matchRequests,
			&istiov1beta1.HTTPMatchRequest{
				Uri: uri,
				Authority: &istiov1beta1.StringMatch{
					MatchType: &istiov1beta1.StringMatch_Regex{
						Regex: constants.HostRegExp(targetHost),
					},
				},
				Gateways: []string{config.IngressGateway},
			})

		if additionalHosts != nil && len(*additionalHosts) != 0 {
			for _, host := range *additionalHosts {
				matchRequest := &istiov1beta1.HTTPMatchRequest{
					Uri: uri,
					Authority: &istiov1beta1.StringMatch{
						MatchType: &istiov1beta1.StringMatch_Regex{
							Regex: constants.HostRegExp(host),
						},
					},
					Gateways: []string{config.IngressGateway},
				}
				if !containsHTTPMatchRequest(matchRequest, matchRequests) {
					matchRequests = append(matchRequests, matchRequest)
				}
			}
		}
	}
	return matchRequests
}

func containsHTTPMatchRequest(matchRequest *istiov1beta1.HTTPMatchRequest, matchRequests []*istiov1beta1.HTTPMatchRequest) bool {
	for _, matchRequestEle := range matchRequests {
		// If authority, gateways and uri are all equal, two HTTPMatchRequests will be equal.
		if stringMatchEqual(matchRequest.Authority, matchRequestEle.Authority) && gatewaysEqual(matchRequest, matchRequestEle) &&
			stringMatchEqual(matchRequest.Uri, matchRequestEle.Uri) {
			return true
		}
	}
	return false
}

func stringMatchEqual(stringMatch, stringMatchDest *istiov1beta1.StringMatch) bool {
	if stringMatch != nil && stringMatchDest != nil {
		return equality.Semantic.DeepEqual(stringMatch.MatchType, stringMatchDest.MatchType)
	}
	if stringMatch == nil && stringMatchDest == nil {
		return true
	}
	return false
}

func gatewaysEqual(matchRequest, matchRequestDest *istiov1beta1.HTTPMatchRequest) bool {
	return equality.Semantic.DeepEqual(matchRequest.Gateways, matchRequestDest.Gateways)
}

func createIngress(isvc *v1beta1.InferenceService, useDefault bool, config *v1beta1.IngressConfig, domainList *[]string, deployConfig *v1beta1.DeployConfig) *istioclientv1beta1.VirtualService {
	if !isvc.Status.IsConditionReady(v1beta1.PredictorReady) {
		status := corev1.ConditionFalse
		if isvc.Status.IsConditionUnknown(v1beta1.PredictorReady) {
			status = corev1.ConditionUnknown
		}
		isvc.Status.SetCondition(v1beta1.IngressReady, &apis.Condition{
			Type:   v1beta1.IngressReady,
			Status: status,
			Reason: "Predictor ingress not created",
		})
		return nil
	}
	backend := constants.PredictorServiceName(isvc.Name)
	if useDefault {
		backend = constants.DefaultPredictorServiceName(isvc.Name)
	}

	if isvc.Spec.Transformer != nil {
		backend = constants.TransformerServiceName(isvc.Name)
		if useDefault {
			backend = constants.DefaultTransformerServiceName(isvc.Name)
		}
		if !isvc.Status.IsConditionReady(v1beta1.TransformerReady) {
			status := corev1.ConditionFalse
			if isvc.Status.IsConditionUnknown(v1beta1.TransformerReady) {
				status = corev1.ConditionUnknown
			}
			isvc.Status.SetCondition(v1beta1.IngressReady, &apis.Condition{
				Type:   v1beta1.IngressReady,
				Status: status,
				Reason: "Transformer ingress not created",
			})
			return nil
		}
	}
	isInternal := false
	serviceHost := getServiceHost(isvc)
	// if service is labelled with cluster local or knative domain is configured as internal
	if val, ok := isvc.Labels[constants.VisibilityLabel]; ok && val == constants.ClusterLocalVisibility {
		isInternal = true
	}
	serviceInternalHostName := network.GetServiceHostname(isvc.Name, isvc.Namespace)
	if serviceHost == serviceInternalHostName {
		isInternal = true
	}
	httpRoutes := []*istiov1beta1.HTTPRoute{}
	// Build explain route
	expBackend := constants.ExplainerServiceName(isvc.Name)
	if useDefault {
		expBackend = constants.DefaultExplainerServiceName(isvc.Name)
	}

	additionalHosts := &[]string{}
	hosts := []string{
		network.GetServiceHostname(isvc.Name, isvc.Namespace),
	}
	if !isInternal {
		getAdditionalHosts(domainList, serviceHost, config, additionalHosts)
	}

	if isvc.Spec.Explainer != nil {
		if !isvc.Status.IsConditionReady(v1beta1.ExplainerReady) {
			status := corev1.ConditionFalse
			if isvc.Status.IsConditionUnknown(v1beta1.ExplainerReady) {
				status = corev1.ConditionUnknown
			}
			isvc.Status.SetCondition(v1beta1.IngressReady, &apis.Condition{
				Type:   v1beta1.IngressReady,
				Status: status,
				Reason: "Explainer ingress not created",
			})
			return nil
		}
		explainerRouter := istiov1beta1.HTTPRoute{
			Match: createHTTPMatchRequest(constants.ExplainPrefix(), serviceHost,
				network.GetServiceHostname(isvc.Name, isvc.Namespace), additionalHosts, isInternal, config),
			Route: []*istiov1beta1.HTTPRouteDestination{
				createHTTPRouteDestination(config.LocalGatewayServiceName),
			},
			Headers: &istiov1beta1.Headers{
				Request: &istiov1beta1.Headers_HeaderOperations{
					Set: map[string]string{
						"Host": network.GetServiceHostname(expBackend, isvc.Namespace),
					},
				},
			},
		}
		httpRoutes = append(httpRoutes, &explainerRouter)
	}
	// Add predict route
	httpRoutes = append(httpRoutes, &istiov1beta1.HTTPRoute{
		Match: createHTTPMatchRequest("", serviceHost,
			network.GetServiceHostname(isvc.Name, isvc.Namespace), additionalHosts, isInternal, config),
		Route: []*istiov1beta1.HTTPRouteDestination{
			createHTTPRouteDestination(config.LocalGatewayServiceName),
		},
		Headers: &istiov1beta1.Headers{
			Request: &istiov1beta1.Headers_HeaderOperations{
				Set: map[string]string{
					"Host": network.GetServiceHostname(backend, isvc.Namespace),
				},
			},
		},
	})

	gateways := []string{
		config.LocalGateway,
		constants.IstioMeshGateway,
	}
	if !isInternal {
		hosts = append(hosts, serviceHost)
		gateways = append(gateways, config.IngressGateway)
	}

	if config.PathTemplate != "" {
		path, err := GenerateUrlPath(isvc.Name, isvc.Namespace, config)
		if err != nil {
			log.Error(err, "Failed to generate URL from pathTemplate")
			return nil
		}
		url := &apis.URL{}
		url.Path = strings.TrimSuffix(path, "/") // remove trailing "/" if present
		url.Host = config.IngressDomain
		// In this case, we have a path-based URL so we add a path-based rule
		httpRoutes = append(httpRoutes, &istiov1beta1.HTTPRoute{
			Match: []*istiov1beta1.HTTPMatchRequest{
				{
					Uri: &istiov1beta1.StringMatch{
						MatchType: &istiov1beta1.StringMatch_Prefix{
							Prefix: url.Path + "/",
						},
					},
					Authority: &istiov1beta1.StringMatch{
						MatchType: &istiov1beta1.StringMatch_Regex{
							Regex: constants.HostRegExp(url.Host),
						},
					},
					Gateways: []string{config.IngressGateway},
				},
				{
					Uri: &istiov1beta1.StringMatch{
						MatchType: &istiov1beta1.StringMatch_Exact{
							Exact: url.Path,
						},
					},
					Authority: &istiov1beta1.StringMatch{
						MatchType: &istiov1beta1.StringMatch_Regex{
							Regex: constants.HostRegExp(url.Host),
						},
					},
					Gateways: []string{config.IngressGateway},
				},
			},
			Rewrite: &istiov1beta1.HTTPRewrite{
				Uri: "/",
			},
			Route: []*istiov1beta1.HTTPRouteDestination{
				createHTTPRouteDestination(config.LocalGatewayServiceName),
			},
			Headers: &istiov1beta1.Headers{
				Request: &istiov1beta1.Headers_HeaderOperations{
					Set: map[string]string{
						"Host": network.GetServiceHostname(backend, isvc.Namespace),
					},
				},
			},
		})
		// Include ingressDomain to the domains (both internal and external) derived by KNative
		hosts = append(hosts, url.Host)
	}

	if !isInternal {
		// We only append the additional hosts, when the ingress is not internal.
		hostMap := map[string]bool{}
		for _, host := range hosts {
			hostMap[host] = true
		}

		for _, additionalHost := range *additionalHosts {
			if !hostMap[additionalHost] {
				hosts = append(hosts, additionalHost)
			}
		}
	}
	annotations := utils.Filter(isvc.Annotations, func(key string) bool {
		return !utils.Includes(deployConfig.ServiceAnnotationDisallowedList, key)
	})
	desiredIngress := &istioclientv1beta1.VirtualService{
		ObjectMeta: metav1.ObjectMeta{
			Name:        isvc.Name,
			Namespace:   isvc.Namespace,
			Annotations: annotations,
			Labels:      isvc.Labels,
		},
		Spec: istiov1beta1.VirtualService{
			Hosts:    hosts,
			Gateways: gateways,
			Http:     httpRoutes,
		},
	}
	return desiredIngress
}

// getDomainList gets all the available domain names available with Knative Serving.
func getDomainList(clientset kubernetes.Interface) *[]string {
	res := new([]string)
	ns := constants.DefaultNSKnativeServing
	if namespace := os.Getenv(system.NamespaceEnvKey); namespace != "" {
		ns = namespace
	}

	// Leverage the clientset to access the configMap to get all the available domain names
	configMap, err := clientset.CoreV1().ConfigMaps(ns).Get(context.TODO(),
		config.DomainConfigName, metav1.GetOptions{})
	if err != nil {
		return res
	}
	for domain := range configMap.Data {
		*res = append(*res, domain)
	}
	return res
}

func (ir *IngressReconciler) Reconcile(isvc *v1beta1.InferenceService) error {
	serviceHost := getServiceHost(isvc)
	serviceUrl := getServiceUrl(isvc, ir.ingressConfig)
	disableIstioVirtualHost := ir.ingressConfig.DisableIstioVirtualHost
	if serviceHost == "" || serviceUrl == "" {
		return nil
	}
	// When Istio virtual host is disabled, we return the underlying component url.
	// When Istio virtual host is enabled. we return the url using inference service virtual host name and redirect to the corresponding transformer, predictor or explainer url.
	if !disableIstioVirtualHost {
		// Check if existing knative service name has default suffix
		defaultNameExisting := &knservingv1.Service{}
		useDefault := false
		err := ir.client.Get(context.TODO(), types.NamespacedName{Name: constants.DefaultPredictorServiceName(isvc.Name), Namespace: isvc.Namespace}, defaultNameExisting)
		if err == nil {
			useDefault = true
		}
		domainList := getDomainList(ir.clientset)
		desiredIngress := createIngress(isvc, useDefault, ir.ingressConfig, domainList, ir.deployConfig)
		if desiredIngress == nil {
			return nil
		}

		// Create external service which points to local gateway
		if err := ir.reconcileExternalService(isvc, ir.ingressConfig); err != nil {
			return errors.Wrapf(err, "fails to reconcile external name service")
		}

		if err := controllerutil.SetControllerReference(isvc, desiredIngress, ir.scheme); err != nil {
			return errors.Wrapf(err, "fails to set owner reference for ingress")
		}

		existing := &istioclientv1beta1.VirtualService{}
		err = ir.client.Get(context.TODO(), types.NamespacedName{Name: desiredIngress.Name, Namespace: desiredIngress.Namespace}, existing)
		if err != nil {
			if apierr.IsNotFound(err) {
				log.Info("Creating Ingress for isvc", "namespace", desiredIngress.Namespace, "name", desiredIngress.Name)
				err = ir.client.Create(context.TODO(), desiredIngress)
			}
		} else {
			if !routeSemanticEquals(desiredIngress, existing) {
				deepCopy := existing.DeepCopy()
				deepCopy.Spec = *desiredIngress.Spec.DeepCopy()
				deepCopy.Annotations = desiredIngress.Annotations
				deepCopy.Labels = desiredIngress.Labels
				log.Info("Update Ingress for isvc", "namespace", desiredIngress.Namespace, "name", desiredIngress.Name)
				err = ir.client.Update(context.TODO(), deepCopy)
			}
		}
		if err != nil {
			return errors.Wrapf(err, "fails to create or update ingress")
		}
	}

	if url, err := apis.ParseURL(serviceUrl); err == nil {
		isvc.Status.URL = url
		var hostPrefix string
		if disableIstioVirtualHost {
			// Check if existing kubernetes service name has default suffix
			existingServiceWithDefaultSuffix := &corev1.Service{}
			useDefault := false
			err := ir.client.Get(context.TODO(), types.NamespacedName{Name: constants.DefaultPredictorServiceName(isvc.Name), Namespace: isvc.Namespace}, existingServiceWithDefaultSuffix)
			if err == nil {
				useDefault = true
			}
			hostPrefix = getHostPrefix(isvc, disableIstioVirtualHost, useDefault)
		} else {
			hostPrefix = getHostPrefix(isvc, disableIstioVirtualHost, false)
		}

		isvc.Status.Address = &duckv1.Addressable{
			URL: &apis.URL{
				Host:   network.GetServiceHostname(hostPrefix, isvc.Namespace),
				Scheme: "http",
			},
		}
		isvc.Status.SetCondition(v1beta1.IngressReady, &apis.Condition{
			Type:   v1beta1.IngressReady,
			Status: corev1.ConditionTrue,
		})
		return nil
	} else {
		return errors.Wrapf(err, "fails to parse service url")
	}
}

func routeSemanticEquals(desired, existing *istioclientv1beta1.VirtualService) bool {
	return cmp.Equal(desired.Spec.DeepCopy(), existing.Spec.DeepCopy(), protocmp.Transform()) &&
		equality.Semantic.DeepEqual(desired.ObjectMeta.Labels, existing.ObjectMeta.Labels) &&
		equality.Semantic.DeepEqual(desired.ObjectMeta.Annotations, existing.ObjectMeta.Annotations)
}

func getHostPrefix(isvc *v1beta1.InferenceService, disableIstioVirtualHost bool, useDefault bool) string {
	if disableIstioVirtualHost {
		if useDefault {
			if isvc.Spec.Transformer != nil {
				return constants.DefaultTransformerServiceName(isvc.Name)
			}
			return constants.DefaultPredictorServiceName(isvc.Name)
		} else {
			if isvc.Spec.Transformer != nil {
				return constants.TransformerServiceName(isvc.Name)
			}
			return constants.PredictorServiceName(isvc.Name)
		}
	}
	return isvc.Name
}
